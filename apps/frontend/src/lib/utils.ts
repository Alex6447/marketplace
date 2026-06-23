import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Объединяет классы Tailwind, корректно разрешая конфликты (shadcn-утилита). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
