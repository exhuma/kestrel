<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { UserManager } from 'oidc-client-ts'
import { initAuth } from '../auth/oidc'
import { useIdentity } from '../composables/useIdentity'

// Two independent identity sources, never both active at once:
//
// - oauth2-proxy (existing, informational-only): the backend reflects
//   forwarded headers verbatim; kestrel performs no authentication of its
//   own in this mode. Hidden entirely when no proxy is in front.
// - OIDC (feature 011, KESTREL_AUTH_ENABLED): when the app has mounted at
//   all, the visitor is already signed in — main.ts's bootstrap gates
//   mounting behind sign-in itself, so there is no in-app "log in" state
//   to render here, only "who am I" plus a sign-out control.
const { identity } = useIdentity()

const oidcEnabled = ref(false)
const oidcDisplayName = ref('')
let userManager: UserManager | null = null

onMounted(async () => {
  const auth = await initAuth()
  oidcEnabled.value = auth.enabled
  if (!auth.enabled || !auth.userManager) return
  userManager = auth.userManager
  const user = await auth.userManager.getUser()
  const profile = user?.profile
  oidcDisplayName.value =
    (profile?.preferred_username as string | undefined) ||
    (profile?.email as string | undefined) ||
    (profile?.sub as string | undefined) ||
    ''
})

const displayName = computed(() =>
  oidcEnabled.value
    ? oidcDisplayName.value
    : identity.value?.preferred_username ||
      identity.value?.username ||
      identity.value?.email ||
      '',
)

async function signOut(): Promise<void> {
  await userManager?.signoutRedirect()
}
</script>

<template>
  <v-tooltip v-if="displayName" :text="identity?.email || displayName">
    <template #activator="{ props }">
      <v-chip
        v-bind="props"
        variant="tonal"
        label
        class="me-2"
        prepend-icon="$account"
        :append-icon="oidcEnabled ? '$close' : undefined"
        @click:append="signOut"
      >
        {{ displayName }}
      </v-chip>
    </template>
  </v-tooltip>
</template>
