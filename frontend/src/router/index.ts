// Addressability (FR-028): board, a request's cockpit, and its interview
// each get their own address, resolvable directly in a fresh session.
// Hash history (research R2) — no server-side route handling needed.
// `board` is eager (the common entry point); `cockpit`/`interview`
// are lazy so the board doesn't pay for their code.
import {
  createRouter,
  createWebHashHistory,
  type RouterHistory,
} from 'vue-router'
import StageBoardView from '../views/StageBoardView.vue'

/** Build the app router; tests inject a memory history. */
export function createAppRouter(
  history: RouterHistory = createWebHashHistory(),
) {
  return createRouter({
    history,
    routes: [
      { path: '/', name: 'board', component: StageBoardView },
      {
        path: '/requests/:id',
        name: 'cockpit',
        component: () => import('../views/RequestCockpitView.vue'),
      },
      {
        path: '/requests/:id/interview',
        name: 'interview',
        component: () => import('../views/InterviewView.vue'),
      },
      {
        path: '/:pathMatch(.*)*',
        name: 'not-found',
        component: () => import('../views/NotFoundView.vue'),
      },
    ],
  })
}

export const router = createAppRouter()
