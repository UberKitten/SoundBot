/**
 * Touch long-press → context-menu helper.
 *
 * iOS Safari never fires `contextmenu` for a long-press, so touch users can't
 * reach the sound context menu. This attaches pointer-event handling: a press
 * held ~500ms without moving fires the callback at the touch point. Scrolling
 * (>10px movement), lifting early, or cancellation aborts the timer.
 *
 * After a long-press fires, the browser still dispatches a synthetic `click`
 * when the finger lifts. That click must not play the sound, must not trigger
 * a menu item that happens to render under the finger, and must not reach the
 * document-level click listener that closes the menu — so exactly ONE click is
 * consumed at capture phase, armed on the release (pointerup) that follows the
 * fire, with a short expiry in case the browser suppresses the click itself.
 *
 * Android DOES fire `contextmenu` on long-press. Whichever fires first wins:
 * if our timer fired, the native contextmenu is swallowed (capture phase); if
 * the native event arrives first, our pending timer is cancelled and the
 * element's normal contextmenu handler opens the menu. Only one menu opens.
 */

const LONG_PRESS_MS = 500;
const MOVE_TOLERANCE_PX = 10;
/** How long after firing we still swallow the trailing native contextmenu. */
const CONTEXTMENU_SUPPRESS_MS = 700;
/** How long after release we wait for the synthetic click before disarming. */
const CLICK_SUPPRESS_MS = 400;

export function attachLongPress(
  el: HTMLElement,
  onLongPress: (clientX: number, clientY: number) => void
): void {
  let timer: number | null = null;
  let pointerId: number | null = null;
  let startX = 0;
  let startY = 0;
  let firedAt = 0;
  /** Pointer whose release should arm the one-shot click swallow. */
  let firedPointerId: number | null = null;

  const cancel = () => {
    if (timer !== null) {
      window.clearTimeout(timer);
      timer = null;
    }
    pointerId = null;
  };

  const armClickSwallow = () => {
    // Consume exactly the one synthetic click that follows the long-press
    // release. Capture phase beats the sound-button handler, menu items, and
    // the document click-closes-menu listener alike.
    const swallowClick = (ce: MouseEvent) => {
      removeSwallow();
      ce.preventDefault();
      ce.stopPropagation();
    };
    const removeSwallow = () => {
      window.clearTimeout(expiry);
      document.removeEventListener("click", swallowClick, true);
    };
    document.addEventListener("click", swallowClick, true);
    // If the browser suppresses the click itself (common on Android after a
    // native long-press), disarm so a later legitimate click isn't eaten.
    const expiry = window.setTimeout(removeSwallow, CLICK_SUPPRESS_MS);
  };

  const fire = (id: number, x: number, y: number) => {
    timer = null;
    pointerId = null;
    firedAt = Date.now();
    firedPointerId = id;

    if (navigator.vibrate) navigator.vibrate(10);
    onLongPress(x, y);
  };

  el.addEventListener("pointerdown", (e: PointerEvent) => {
    // Mouse users have real right-click; only arm for touch/pen.
    if (e.pointerType === "mouse") return;
    // Second concurrent pointer (pinch) — abort.
    if (pointerId !== null) {
      cancel();
      return;
    }
    pointerId = e.pointerId;
    startX = e.clientX;
    startY = e.clientY;
    const id = e.pointerId;
    const x = e.clientX;
    const y = e.clientY;
    timer = window.setTimeout(() => fire(id, x, y), LONG_PRESS_MS);
  });

  el.addEventListener("pointermove", (e: PointerEvent) => {
    if (timer === null || e.pointerId !== pointerId) return;
    // Touch-scroll must never trigger the menu.
    if (
      Math.abs(e.clientX - startX) > MOVE_TOLERANCE_PX ||
      Math.abs(e.clientY - startY) > MOVE_TOLERANCE_PX
    ) {
      cancel();
    }
  });

  el.addEventListener("pointerup", (e: PointerEvent) => {
    if (e.pointerId === firedPointerId) {
      // Finger lifted after the menu opened — the synthetic click is imminent.
      firedPointerId = null;
      armClickSwallow();
      return;
    }
    if (e.pointerId === pointerId) cancel();
  });

  const abort = (e: PointerEvent) => {
    if (e.pointerId === firedPointerId) {
      // Cancelled pointers produce no click; nothing to swallow.
      firedPointerId = null;
      return;
    }
    if (e.pointerId === pointerId) cancel();
  };
  el.addEventListener("pointercancel", abort);
  el.addEventListener("pointerleave", (e: PointerEvent) => {
    if (e.pointerId === pointerId) cancel();
  });

  // Android's native contextmenu for the same long-press: swallow it if ours
  // already fired; otherwise let it through and stand down.
  el.addEventListener(
    "contextmenu",
    (e: MouseEvent) => {
      if (Date.now() - firedAt < CONTEXTMENU_SUPPRESS_MS) {
        e.preventDefault();
        e.stopImmediatePropagation();
      } else if (timer !== null) {
        cancel();
      }
    },
    true
  );
}
