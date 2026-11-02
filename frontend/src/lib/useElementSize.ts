import { useEffect, useState } from 'react';
import type { RefObject } from 'react';

export interface Size {
  width: number;
  height: number;
}

/**
 * Track an element's rendered size with a `ResizeObserver`.
 *
 * Returns `{ width: 0, height: 0 }` until the element is first measured, and in
 * environments without layout (such as jsdom). Used to place rotated video frames, which
 * must be sized from their container's actual pixel box.
 */
export function useElementSize(ref: RefObject<HTMLElement | null>): Size {
  const [size, setSize] = useState<Size>({ width: 0, height: 0 });
  useEffect(() => {
    const element = ref.current;
    if (element === null) return;
    const update = () => {
      setSize({ width: element.clientWidth, height: element.clientHeight });
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return size;
}
