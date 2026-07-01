<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useSessions } from '../composables/useSessions'

const {
  sessions,
  events,
  loading,
  error,
  refresh,
  start,
  resume,
  watchEvents,
} = useSessions()
const prompt = ref('Write a haiku about the sea into poem.txt')
const followUp = ref('Now revise it to be about mountains instead.')
const current = ref<string | null>(null)

onMounted(refresh)

async function onStart(): Promise<void> {
  const id = await start(prompt.value)
  if (id) {
    current.value = id
    watchEvents(id)
  }
}

async function onResume(): Promise<void> {
  if (current.value) {
    const id = await resume(current.value, followUp.value)
    if (id) watchEvents(id)
  }
}
</script>

<template>
  <v-container>
    <v-alert
      v-if="error"
      type="error"
      variant="tonal"
      closable
      class="mb-4"
      @click:close="error = null"
    >
      {{ error }}
    </v-alert>
    <v-row>
      <v-col cols="4">
        <v-textarea v-model="prompt" label="Start prompt" rows="3" />
        <v-btn color="primary" block @click="onStart">Start</v-btn>
        <v-textarea
          v-model="followUp"
          label="Resume input"
          rows="3"
          class="mt-4"
        />
        <v-btn
          color="primary"
          block
          :disabled="!current"
          @click="onResume"
        >
          Resume
        </v-btn>
        <v-list>
          <v-list-item
            v-for="s in sessions"
            :key="s.session_id"
            :title="s.session_id"
            :subtitle="`${s.status} · ${s.event_count} events`"
          />
        </v-list>
      </v-col>
      <v-col cols="8">
        <v-card title="Live events">
          <v-card-text style="font-family: monospace">
            <div v-for="(e, i) in events" :key="i">
              {{ e.type }} — {{ JSON.stringify(e.raw).slice(0, 120) }}
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
    <v-progress-linear
      v-if="loading"
      absolute
      color="primary"
      indeterminate
      location="bottom"
    />
  </v-container>
</template>
