# src/storage/clearner.py
### Modules importation
from pathlib import Path
import shutil

### ------------------------------ Helpers ------------------------------ ###
### Helper : _clear_tts_dir()
def _clear_tts_dir(tts_dir: str = "data/tts") -> None:
    """
    Clear the content of the TTS cache directory.

    This function removes all files and subdirectories inside the given
    directory, while keeping the root directory itself. It is designed
    to be safe to call during UI interactions and will silently ignore
    any deletion errors.

    :param str tts_dir: Path to the TTS cache directory
    :return None: This function does not return anything
    """
    p = Path(tts_dir)

    ### Nothing to do if the path does not exist
    if not p.exists():
        return

    ### Safety check : ensure we only operate on a directory
    if not p.is_dir():
        return

    ### Iterate over all children -> files and subdirectories
    for child in p.iterdir():
        try:
            ### Remove files and symbolic links
            if child.is_file() or child.is_symlink():
                child.unlink()

            ### Recursively remove subdirectories
            else:
                shutil.rmtree(child)
        except Exception:
            ### Ignore errors to avoid breaking the UI flow
            pass
