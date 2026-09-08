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

// happy-dom also lacks visualViewport, which Vuetify's overlay location
// strategy reads when a v-menu/v-tooltip actually opens.
if (!('visualViewport' in globalThis)) {
  ;(globalThis as unknown as { visualViewport: unknown }).visualViewport = {
    width: 1024,
    height: 768,
    offsetLeft: 0,
    offsetTop: 0,
    addEventListener: () => {},
    removeEventListener: () => {},
  }
}
