/**
 * Turns a FastAPI error body into a readable message.
 *
 * FastAPI returns `detail` as a string for HTTPExceptions (e.g. 413, 429) but as an
 * array of `{ loc, msg }` objects for request-validation failures (422).
 */
export function formatApiError(data: unknown, status: number): string {
  const detail = (data as { detail?: unknown } | null | undefined)?.detail;

  if (typeof detail === 'string' && detail) return detail;

  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { loc?: unknown[]; msg?: string } | undefined;
    const where = Array.isArray(first?.loc)
      ? first.loc.filter((p) => p !== 'body').join(' → ')
      : '';
    const msg = first?.msg ?? 'Invalid request';
    const more = detail.length > 1 ? ` (+${detail.length - 1} more)` : '';
    return `${where ? `${where}: ` : ''}${msg}${more}`;
  }

  if (status === 413) return 'The request is too large. Try a smaller workflow.';
  if (status === 422) return 'The workflow is not valid for this request (for example, too many nodes or edges).';
  return `Server error (${status})`;
}
