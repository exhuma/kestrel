// Addressability (FR-028): board, a request's cockpit, and its interview
// each get their own address, resolvable directly in a fresh session.
// Hash history (research R2) — no server-side route handling needed.
// `board` is eager (the common entry point); `cockpit`/`interview`/
// `sessions` are lazy so the board doesn't pay for their code.
import { createRouter, createWebHashHistory } from 'vue-router'
import StageBoardView from '../views/StageBoardView.vue'

export const router = createRouter({
  history: createWebHashHistory(),
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
      path: '/sessions',
      name: 'sessions',
      component: () => import('../views/SessionsView.vue'),
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('../views/NotFoundView.vue'),
    },
  ],
})
