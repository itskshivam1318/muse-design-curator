/** Sets an attribute only when its value changed: a line at rest costs no DOM write per frame. */
export function writeAttr(el: Element, name: string, value: string): void {
  if (el.getAttribute(name) !== value) el.setAttribute(name, value)
}
