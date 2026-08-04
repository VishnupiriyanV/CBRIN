import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

/** clsx + tailwind-merge were already dependencies but never imported anywhere in src/ —
 * this is the standard helper for conditional classNames without conflicting Tailwind
 * utilities silently losing to source order. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
