/** Retrieved docs, filenames, and model text are untrusted. Render as text only — never HTML. */
export function untrustedText(value: unknown, maxLen = 2048): string {
  const text = String(value ?? "")
    .replace(/<[^>]*>/g, "")
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "");
  return text.length > maxLen ? text.slice(0, maxLen) : text;
}
