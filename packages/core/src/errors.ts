/** Safe user-facing errors only; adapters never serialize unknown exceptions or causes. */
export class AppError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) {
    super(message);
    this.name = 'AppError';
  }
}
