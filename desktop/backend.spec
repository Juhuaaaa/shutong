# PyInstaller: the backend as a folder (onedir starts faster and trips antivirus software less than onefile).
from PyInstaller.utils.hooks import collect_submodules

# libarchive is imported lazily and only on Windows; collecting it does not load its DLL.
hidden = (collect_submodules("shutong") + collect_submodules("uvicorn") + collect_submodules("websockets")
          + collect_submodules("send2trash")  # picks its macOS / Windows backend at run time
          + ["libarchive", "libarchive.ffi", "libarchive.read", "libarchive.entry", "libarchive.exception",
             "libarchive.extract", "libarchive.write"])

analysis = Analysis(["backend_entry.py"], pathex=["../backend"], hiddenimports=hidden,
                    excludes=["tkinter", "unittest", "pytest", "test"])
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name="shutong-backend", console=True, upx=False)
COLLECT(exe, analysis.binaries, analysis.datas, name="shutong-backend", upx=False)
