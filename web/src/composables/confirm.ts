/** A yes/no question as a promise, shown by <ConfirmDialog> in App; tests replace this module to answer. */
import { reactive } from "vue";

interface Question {
  title: string;
  text: string;
  danger: boolean;
  resolve: (answer: boolean) => void;
}

export const confirmState = reactive<{ queue: Question[] }>({ queue: [] });

export function ask(title: string, text: string, danger = false): Promise<boolean> {
  return new Promise((resolve) => confirmState.queue.push({ title, text, danger, resolve }));
}

export function answer(value: boolean) {
  confirmState.queue.shift()?.resolve(value);
}
