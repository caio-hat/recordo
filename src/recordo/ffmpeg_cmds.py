"""Builders puros de comandos ffmpeg (sem invocação)."""

from __future__ import annotations

from pathlib import Path


def build_capture_cmd(source: str, output: Path, *, max_seconds: int, bitrate: str) -> list[str]:
    """Captura áudio de uma fonte PulseAudio em Opus."""
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-f",
        "pulse",
        "-i",
        source,
        "-t",
        str(max_seconds),
        "-c:a",
        "libopus",
        "-b:a",
        bitrate,
        "-application",
        "voip",
        "-vbr",
        "on",
        "-y",
        str(output),
    ]


def build_merge_cmd(sys_file: Path, mic_file: Path, output: Path, layout: str, bitrate: str) -> list[str]:
    """Merge mic+sys num único arquivo. layout=merge|split.

    split: sys=canal esquerdo, mic=canal direito (ajuda diarização).
    merge: amerge + loudnorm EBU R128.
    """
    sys_size = sys_file.stat().st_size if sys_file.exists() else 0
    mic_size = mic_file.stat().st_size if mic_file.exists() else 0

    if sys_size == 0 and mic_size == 0:
        return []

    common_out = ["-c:a", "libopus", "-b:a", bitrate, "-application", "voip", "-y", str(output)]

    # Silêncio sintético para canal vazio (se uma fonte falhou)
    silence = ["-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=48000"]
    sys_in = ["-i", str(sys_file)] if sys_size > 0 else silence
    mic_in = ["-i", str(mic_file)] if mic_size > 0 else silence

    base = ["ffmpeg", "-hide_banner", "-loglevel", "warning", *sys_in, *mic_in]

    if layout == "split":
        fcomplex = (
            "[0:a]aformat=channel_layouts=mono,volume=1.0[a];"
            "[1:a]aformat=channel_layouts=mono,volume=1.0[b];"
            "[a][b]join=inputs=2:channel_layout=stereo[out]"
        )
    else:
        fcomplex = (
            "[0:a][1:a]amerge=inputs=2,"
            "aformat=sample_fmts=s16:channel_layouts=stereo,"
            "loudnorm=I=-16:LRA=11:TP=-1.5[out]"
        )

    return [*base, "-filter_complex", fcomplex, "-map", "[out]", *common_out]


def build_concat_cmd(
    segments: list[Path],
    list_path: Path,
    output: Path,
    bitrate: str = "48k",
    *,
    reencode: bool = False,
) -> list[str]:
    """Concatena vários segmentos.

    Por padrão usa `-c copy` — rápido e lossless quando todos os segmentos
    compartilham codec/bitrate/layout (caso normal: gravação com mesmas
    configs do começo ao fim).

    Use `reencode=True` quando segmentos forem heterogêneos (ex: user trocou
    layout merge/split em runtime). O caller (Recorder.finalize) é quem
    detecta a heterogeneidade.
    """
    list_path.write_text("".join(f"file '{p.as_posix()}'\n" for p in segments))
    base = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
    ]
    if reencode:
        return [
            *base,
            "-c:a",
            "libopus",
            "-b:a",
            bitrate,
            "-application",
            "voip",
            "-y",
            str(output),
        ]
    return [*base, "-c", "copy", "-y", str(output)]
