import { ApiError } from '../api/http'

/** The message to show for a failed request. ApiError messages are written for users; anything else is a bug. */
export function userMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  console.error('Unexpected error:', error)
  return 'Something went wrong in the app. Try again, and check the browser console if it keeps happening.'
}
