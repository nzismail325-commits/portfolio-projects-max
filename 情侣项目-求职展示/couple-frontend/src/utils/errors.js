export const DEFAULT_ERROR_MESSAGE = '操作失败，请稍后重试'
export const NETWORK_ERROR_MESSAGE = '网络连接失败，请检查网络状态'
export const TIMEOUT_MESSAGE = '请求超时，请稍后重试'

export const getErrorCode = (error) =>
  error?.response?.data?.code || error?.response?.data?.error_code || ''

export const getErrorMessage = (error, defaultMessage = DEFAULT_ERROR_MESSAGE) => {
  if (error?.code === 'ECONNABORTED') return TIMEOUT_MESSAGE
  if (!error?.response) return NETWORK_ERROR_MESSAGE
  const data = error.response.data
  if (typeof data === 'string' && data.trim()) return data
  return data?.message || data?.msg || data?.error || defaultMessage
}

export const withPrefix = (prefix, message) => {
  if (!prefix) return message || ''
  if (!message) return prefix
  return message.startsWith(prefix) ? message : `${prefix}：${message}`
}
