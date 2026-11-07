import { contextBridge, ipcRenderer, webUtils } from "electron";

contextBridge.exposeInMainWorld("shutong", {
  pathsFor: (files: File[]) => files.map((file) => webUtils.getPathForFile(file)).filter(Boolean),
  pickFolder: (defaultPath?: string) => ipcRenderer.invoke("pick-folder", defaultPath),
  openPath: (path: string) => ipcRenderer.invoke("open-path", path),
  defaultLibraryDir: (kind: string) => ipcRenderer.invoke("default-library-dir", kind),
  trashOriginals: (ids: number[]) => ipcRenderer.invoke("trash-originals", ids),
  openExternal: (url: string) => ipcRenderer.invoke("open-external", url),
  onUpdate: (callback: (info: { version: string; url: string }) => void) => {
    ipcRenderer.on("update", (_event, info) => callback(info));
    ipcRenderer.invoke("get-update").then((info) => info && callback(info));
  },
});
