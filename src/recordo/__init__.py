"""Recordo — frictionless meeting recorder with auto-transcription (TDAH-friendly).

Trocadilho: record (gravar) + recordar (lembrar em pt-BR).
"""

import os as _os

# v0.2.3 — Bug fix UnicodeDecodeError 'ascii' codec can't decode byte 0xc3
# Quando o systemd unit ou shell rodam com LANG=C/POSIX, subprocess.run(text=True)
# usa o locale ASCII e qualquer caractere multibyte (acentos, emoji) explode.
# Forçar UTF-8 no env do processo + dos children resolve no nível raiz.
# Aplicado o mais cedo possível (no import do package) para preceder qualquer
# import pesado (NeMo, transformers, faster-whisper) que possa cachear locale.
for _k, _v in (("LC_ALL", "C.UTF-8"), ("LANG", "C.UTF-8"), ("PYTHONIOENCODING", "utf-8")):
    if not _os.environ.get(_k) or "UTF-8" not in _os.environ.get(_k, "").upper():
        _os.environ[_k] = _v
del _os, _k, _v

__version__ = "0.1.0"
__all__ = ["__version__"]
