/** Short messages at the bottom of the screen (one at a time, queued), shown by App's snackbar. */
import { reactive } from "vue";

export type NotifyKind = "success" | "error" | "info" | "warning";

export const notifyState = reactive<{ queue: { id: number; kind: NotifyKind; text: string }[] }>({ queue: [] });
let next = 0;

function push(kind: NotifyKind, text: string) {
  notifyState.queue.push({ id: ++next, kind, text });
}

export const notify = {
  success: (text: string) => push("success", text),
  error: (text: string) => push("error", text),
  info: (text: string) => push("info", text),
  warning: (text: string) => push("warning", text),
};

export function dismiss() {
  notifyState.queue.shift();
}
