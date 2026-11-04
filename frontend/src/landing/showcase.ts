import type { BoardSummary } from '../api'

/** The recorded demo boards the landing page offers. Ids survive a bundle import, so this is the same locally and deployed. */
export interface ShowcaseBoard {
  boardId: string
  runId: string
  coverItemId: string
  title: string
  line: string
}

export const SHOWCASE: { videoUrl: string | null; boards: ShowcaseBoard[] } = {
  videoUrl: null,
  boards: [
    {
      boardId: 'brd_01m6h989kz0tz8xjvjbp6zbz9x',
      runId: 'arun_01m6h991xyrzxq1xyvhrag2pqk',
      coverItemId: 'itm_01m6h9kv71b9039egsd0hwck3e',
      title: 'A new EV coupe',
      line: 'Vary one thing, keep the rest: views, a drifted wheel put back, three colourways.',
    },
    {
      boardId: 'brd_01m6hcp4q8vrt11mnpw6jrmpb4',
      runId: 'arun_01m6hcpsxzz7fx878hx8fhsn7n',
      coverItemId: 'itm_01m6hcy8231358jakxqx0saprw',
      title: 'What "premium" means',
      line: 'The board pins a vague word to named dimensions, then designs three screens in it.',
    },
    {
      boardId: 'brd_01m6j4rrnz1zzx6qax1rya3j27',
      runId: 'arun_01m6j4sg80tqra73g2y11dvnx9',
      coverItemId: 'itm_01m6j58fb6mb91a1735tea999s',
      title: 'One room, four materials',
      line: 'A Japandi room held still while only material and palette change.',
    },
    {
      boardId: 'brd_01m6j5n5eqdmxv33zhw03qesx5',
      runId: 'arun_01m6j5npnz586e22mbk8vrxat4',
      coverItemId: 'itm_01m6j7p7ayaxf3r0144rmdxgs0',
      title: 'A capsule over two sessions',
      line: 'Five looks that stay in one range, and a look reproduced in a second colour.',
    },
  ],
}

/** The recorded demo boards that exist on this server, in showcase order. */
export function presentShowcase(boards: BoardSummary[] | undefined): ShowcaseBoard[] {
  const here = new Set((boards ?? []).map((b) => b.id))
  return SHOWCASE.boards.filter((b) => here.has(b.boardId))
}
