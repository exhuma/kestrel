<script setup lang="ts">
import { computed, ref } from 'vue'
import SessionPanel from './components/SessionPanel.vue'
import WorkflowPanel from './components/WorkflowPanel.vue'
import { useSessions } from './composables/useSessions'

// Shared composable state: the header reflects fleet-wide status.
const { sessions } = useSessions()
const running = computed(() =>
  sessions.value.some((s) => s.status === 'running'),
)

const view = ref<'sessions' | 'workflows'>('sessions')
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <img src="/logo.svg" alt="agent-dispatcher logo" height="40" class="ms-2" />
        <span class="brand__name">agent<span class="brand__dot">·</span>dispatcher</span>
        <span class="brand__tag mono">mission control</span>
      </div>
      <nav class="viewnav">
        <button class="viewnav__btn" :class="{ 'viewnav__btn--on': view === 'sessions' }"
          @click="view = 'sessions'">Sessions</button>
        <button class="viewnav__btn" :class="{ 'viewnav__btn--on': view === 'workflows' }"
          @click="view = 'workflows'">Workflows</button>
      </nav>
      <div class="status" :class="running ? 'status--live' : 'status--idle'">
        <span class="status__dot" />
        <span class="status__label mono">{{ running ? 'live' : 'idle' }}</span>
      </div>
    </header>
    <main class="stageroot">
      <SessionPanel v-if="view === 'sessions'" />
      <WorkflowPanel v-else />
    </main>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  background:
    radial-gradient(
      1100px 420px at 78% -8%,
      rgba(53, 230, 201, 0.06),
      transparent 60%
    ),
    var(--ink-900);
}

.topbar {
  height: var(--header-h);
  flex: none;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 22px;
  padding: 0 24px;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--ink-850) 82%, transparent);
  backdrop-filter: blur(8px);
}

.brand {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.brand__mark {
  position: relative;
  align-self: center;
  width: 22px;
  height: 22px;
  border: 1.5px solid var(--line);
  border-radius: 50%;
  display: grid;
  place-items: center;
}
.brand__mark::before {
  content: '';
  position: absolute;
  inset: 4px;
  border: 1.5px solid var(--signal);
  border-radius: 50%;
  opacity: 0.55;
}
.brand__name {
  font-weight: 700;
  font-size: 15.5px;
  letter-spacing: 0.01em;
}
.brand__dot {
  color: var(--signal);
  padding: 0 1px;
}
.brand__tag {
  font-size: 10.5px;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: var(--text-dim);
}

.viewnav { display: flex; gap: 4px; margin-left: 22px; }
.viewnav__btn {
  background: transparent; border: 1px solid var(--line); color: var(--text-mid);
  border-radius: 999px; padding: 5px 14px; font-size: 12.5px; cursor: pointer;
  font-family: var(--font-sans);
}
.viewnav__btn--on { color: var(--signal-ink); background: var(--signal); border-color: var(--signal); }

.status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px 5px 10px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--ink-800);
  margin-left: auto;
}
.status__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.status__label {
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}
.status--idle .status__dot {
  background: var(--idle);
}
.status--idle .status__label {
  color: var(--text-mid);
}
.status--live .status__dot {
  background: var(--run);
  box-shadow: 0 0 0 0 var(--signal-glow);
  animation: pulse 1.8s ease-out infinite;
}
.status--live .status__label {
  color: var(--run);
}

@keyframes pulse {
  0% {
    box-shadow: 0 0 0 0 rgba(53, 230, 201, 0.45);
  }
  70% {
    box-shadow: 0 0 0 7px rgba(53, 230, 201, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(53, 230, 201, 0);
  }
}

.stageroot {
  flex: 1;
  min-height: 0;
}

@media (max-width: 620px) {
  .brand__tag {
    display: none;
  }
  .topbar {
    padding: 0 16px;
  }
}
</style>
