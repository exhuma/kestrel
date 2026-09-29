/**
 * A shared, coarse clock for "how long ago" labels (feature 033): one
 * timer for the whole app, running only while something uses it.
 */
import { onScopeDispose, ref } from 'vue'

const now = ref(Date.now())
let users = 0
let timer: ReturnType<typeof setInterval> | null = null

export function useNow(intervalMs = 30000) {
  users += 1
  if (timer === null) {
    timer = setInterval(() => {
      now.value = Date.now()
    }, intervalMs)
  }
  onScopeDispose(() => {
    users -= 1
    if (users === 0 && timer !== null) {
      clearInterval(timer)
      timer = null
    }
  })
  return now
}
