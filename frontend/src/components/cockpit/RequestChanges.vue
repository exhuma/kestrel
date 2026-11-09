<script setup lang="ts">
// Sends delivered work back for more: the reviewer says what should
// change, and the coder works on it on the same branch. The dialog stays
// open when the server refuses, so what was written is not lost.
import { computed, ref } from 'vue'
import { useBoard } from '../../composables/useBoard'

const { requestChanges } = useBoard()

const open = ref(false)
const feedback = ref('')
const busy = ref(false)
const refused = ref<string | null>(null)

const canSubmit = computed(() => feedback.value.trim().length > 0)

function start(): void {
  feedback.value = ''
  refused.value = null
  open.value = true
}

async function submit(): Promise<void> {
  if (!canSubmit.value) return
  busy.value = true
  refused.value = await requestChanges(feedback.value.trim())
  busy.value = false
  if (refused.value === null) open.value = false
}
</script>

<template>
  <v-sheet
    class="d-flex align-center flex-wrap ga-3 pa-3"
    rounded
    data-testid="request-changes"
  >
    <span class="text-body-2 flex-1-1">
      Not happy with what was delivered? Say what should change, and it goes
      back to the coder.
    </span>
    <v-btn variant="tonal" @click="start">Request changes</v-btn>

    <v-dialog v-model="open" max-width="640" persistent>
      <v-card>
        <v-card-title>Request changes</v-card-title>
        <v-card-text>
          <p class="mb-3">
            The coder works on this on the same branch and the verifier checks
            it. The same merge or pull request is then updated.
          </p>
          <v-textarea
            v-model="feedback"
            label="What should change"
            rows="6"
            autofocus
          />
          <v-alert v-if="refused" type="error" density="compact">
            {{ refused }}
          </v-alert>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" :disabled="busy" @click="open = false">
            Cancel
          </v-btn>
          <v-btn
            color="primary"
            :disabled="!canSubmit"
            :loading="busy"
            @click="submit"
          >
            Request changes
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-sheet>
</template>
