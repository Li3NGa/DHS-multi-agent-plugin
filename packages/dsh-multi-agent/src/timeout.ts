/** Shared validation for public run-level timeout options. */

/**
 * Validate a run-level timeout. `undefined` means no whole-run timeout;
 * configured values must be finite and strictly positive.
 */
export function validateTimeoutMs(value: unknown, field = 'timeoutMs'): asserts value is number | undefined {
  if (
    value !== undefined &&
    (typeof value !== 'number' || !Number.isFinite(value) || value <= 0)
  ) {
    throw new TypeError(`${field} must be a finite number > 0`)
  }
}
