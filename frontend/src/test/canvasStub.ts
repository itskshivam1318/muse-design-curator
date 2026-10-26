/** jsdom has no 2D canvas; give Konva a context whose every method is a no-op. */
export function stubCanvasContext(): void {
  const noop = () => {}
  const ctx = new Proxy(
    {},
    {
      get: (_t, key) => {
        if (key === 'measureText') return () => ({ width: 10 })
        if (key === 'getImageData' || key === 'createImageData') return () => ({ data: new Uint8ClampedArray(4) })
        if (key === 'createLinearGradient' || key === 'createRadialGradient' || key === 'createPattern')
          return () => ({ addColorStop: noop })
        return noop
      },
      set: () => true,
    },
  )
  HTMLCanvasElement.prototype.getContext = (() => ctx) as unknown as HTMLCanvasElement['getContext']
}
