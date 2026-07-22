function normalizeToolResultText(value) {
  return String(value || '').trim().replace(/\s+/g, ' ').toLowerCase()
}

export function shouldRenderToolOutput(output, error) {
  const normalizedOutput = normalizeToolResultText(output)
  const normalizedError = normalizeToolResultText(error)

  if (!normalizedOutput) return false
  if (!normalizedError) return true
  return normalizedOutput !== normalizedError && normalizedOutput !== `error: ${normalizedError}`
}
