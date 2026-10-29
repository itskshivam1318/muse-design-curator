/** Canvas glue for plugin nodes: items dragged onto a node, and a note's Send to node. */
import { type QueryClient, useQueryClient } from '@tanstack/react-query'
import { useMemo } from 'react'
import { type Item, keys, type NodesResponse, type PluginInfo, type Point } from '../api'
import { itemBounds } from '../canvas/nodeProps'
import { addToNode, createNodeWith, nodeAt, placeNode } from './nodeLogic'
import { dropTargetStore, nodeNoticeStore } from './stores'

/**
 * For the canvas's item drag: `hover` marks the node under the pointer; `drop` adds the items to
 * that node's inputs and returns true (the items then go back where they were) or returns false.
 */
export function useNodeDrop(boardId: string, readOnly = false) {
  const qc = useQueryClient()
  return useMemo(() => {
    const under = (p: Point | null) => {
      const nodes = qc.getQueryData<NodesResponse>(keys.nodes(boardId))?.nodes ?? []
      return readOnly || !p ? null : nodeAt(nodes, p)
    }
    return {
      hover(p: Point | null) {
        dropTargetStore.set(under(p)?.id ?? null)
      },
      drop(p: Point | null, itemIds: readonly string[]): boolean {
        dropTargetStore.set(null)
        const node = under(p)
        if (!node) return false
        void addToNode(qc, node.id, itemIds).then(
          (r) => r.notice && nodeNoticeStore.set(r.notice),
          () => nodeNoticeStore.set('Could not add the items to the node'),
        )
        return true
      },
    }
  }, [qc, boardId, readOnly])
}

/** A note's ⋯ → Send to node: a new node of that plugin beside the note, with the note as its input. */
export async function sendNoteToNode(qc: QueryClient, boardId: string, pluginId: string, noteId: string): Promise<void> {
  const plugin = qc.getQueryData<PluginInfo[]>(keys.plugins())?.find((p) => p.id === pluginId)
  const note = qc.getQueryData<Item[]>(keys.items(boardId))?.find((i) => i.id === noteId)
  if (!plugin || !note) return
  try {
    await createNodeWith(qc, boardId, plugin, placeNode(itemBounds(note), { x: 0, y: 0 }), [noteId])
  } catch {
    nodeNoticeStore.set(`Could not add a ${plugin.name} node`)
  }
}
