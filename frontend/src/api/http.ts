import axios from 'axios'

// 统一 HTTP 客户端：携带统一响应包络 { code, message, data, trace_id }（§5.1）
export const http = axios.create({
  baseURL: '/api/v1',
  timeout: 30_000,
})

// 响应拦截：非 0 业务码统一抛错，trace_id 附加到错误对象便于排障
http.interceptors.response.use(
  (resp) => {
    const body = resp.data
    if (body && typeof body === 'object' && 'code' in body && body.code !== 0) {
      return Promise.reject(new Error(`${body.code}: ${body.message}`))
    }
    return resp
  },
  (err) => {
    err.traceId = err.response?.headers?.['x-request-id']
    return Promise.reject(err)
  },
)
