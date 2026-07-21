// Global test setup. happy-dom lacks ResizeObserver, which several Vuetify
// components (v-tabs slider, overlays) construct on mount. Provide a no-op
// stub so mounting those components does not throw.
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

if (!('ResizeObserver' in globalThis)) {
  ;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver =
    ResizeObserverStub
}
