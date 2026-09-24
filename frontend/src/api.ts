export type User = { id: string; username: string; display_name: string }
export type Workspace = { id: string; name: string; owner_id: string; created_at: string }
export type Project = { id: string; workspace_id: string; name: string; description: string; provider_id?: string | null }
export type Conversation = { id: string; project_id: string; title: string; created_at: string }
export type Message = { id: string; role: string; content: string; run_id?: string | null; created_at: string }
export type Run = { id: string; project_id: string; conversation_id?: string | null; kind: string; status: string; input: Record<string, unknown>; output: Record<string, unknown>; error?: string | null; created_at: string }
export type Document = { id: string; title: string; version_no: number; parse_status: string; index_status: string; chunk_count: number; embedded: boolean; created_at: string }
export type SearchResult = { chunk_id: string; document_id: string; document_version_id: string; document_title: string; page_number?: number | null; paragraph_index?: number | null; snippet: string; vector_score?: number | null; keyword_score?: number | null; final_score: number; methods: string[] }
export type Fact = { id: string; project_id: string; subject_text: string; predicate: string; object_text: string; status: string; confidence?: number | null; valid_from?: string | null; valid_to?: string | null; recorded_at?: string | null; evidence_ref_id?: string | null; created_at: string }
export type ReviewItem = { id: string; project_id: string; item_type: string; ref_id: string; reason: string; status: string; created_at: string; resolution: string }
export type Memory = { id: string; user_id: string; key: string; value: string; status: string; confidence: number; created_at: string; updated_at: string; retracted_at?: string | null }
export type Provider = { id: string; workspace_id: string; name: string; provider_type: 'openai_compatible' | 'ollama' | 'vllm' | string; base_url: string; chat_model: string; embedding_model: string; has_api_key: boolean; capabilities: Record<string, unknown>; is_default: boolean; created_at?: string; updated_at?: string }

const API_BASE = import.meta.env.VITE_API_BASE || ''

function token() { return localStorage.getItem('oliveira_token') || '' }

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  if (token()) headers.set('Authorization', `Bearer ${token()}`)
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(detail.detail || `请求失败（${response.status}）`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export function isLoggedIn() { return Boolean(token()) }
export function saveToken(value: string) { localStorage.setItem('oliveira_token', value) }
export function clearToken() { localStorage.removeItem('oliveira_token') }

export async function login(payload: { username: string; password: string }) { const result = await api<{ access_token: string; user: User }>('/api/v1/auth/login', { method: 'POST', body: JSON.stringify(payload) }); saveToken(result.access_token); return result.user }
export async function register(payload: { username: string; password: string; display_name: string }) { const result = await api<{ access_token: string; user: User }>('/api/v1/auth/register', { method: 'POST', body: JSON.stringify(payload) }); saveToken(result.access_token); return result.user }
export async function me() { return api<User>('/api/v1/auth/me') }
