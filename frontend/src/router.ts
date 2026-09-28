import { createRouter, createWebHistory } from 'vue-router'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: () => import('./views/HomeView.vue') },
    { path: '/confirm', component: () => import('./views/ConfirmView.vue') },
    { path: '/solution/:id', component: () => import('./views/SolutionView.vue') },
    { path: '/practice/:setId', component: () => import('./views/PracticeView.vue') },
    { path: '/practice/:setId/result', component: () => import('./views/ResultView.vue') },
    { path: '/mistakes', component: () => import('./views/MistakesView.vue') },
    { path: '/history', component: () => import('./views/HistoryView.vue') },
    { path: '/auth', component: () => import('./views/LoginView.vue') },
  ],
})
