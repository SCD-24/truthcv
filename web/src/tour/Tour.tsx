import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import { TOUR_STEPS } from "./steps";

const CARD_WIDTH = 320;
const MARGIN = 12;

/**
 * A coach-mark guided tour. It walks through TOUR_STEPS, resolving each step's
 * `data-tour` anchor in the live DOM, highlighting it with a ring and floating
 * an explanatory card beside it. Steps can carry a `navigateTo` route, which
 * the tour follows before resolving the anchor. A step whose anchor never
 * appears is skipped automatically so the tour can never stall.
 */
export function Tour({ onDone }: { onDone: () => void }) {
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const location = useLocation();
  const navigate = useNavigate();

  // Keep the latest callbacks in refs so the resolver effect can depend only on
  // the step index and the current path — not on the identity of `onDone` or
  // `navigate`, which would otherwise re-run it every render and, since each run
  // sets a fresh DOMRect, spin into a render loop.
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;

  const step = TOUR_STEPS[index];
  const isFirst = index === 0;
  const isLast = index === TOUR_STEPS.length - 1;

  // Resolve the current step's anchor, navigating first when the step lives on
  // another page. Retries once (to let the DOM settle after navigation) and, if
  // the anchor still isn't there, skips the step rather than blocking.
  useEffect(() => {
    if (!step) return;

    if (step.navigateTo && step.navigateTo !== location.pathname) {
      navigateRef.current(step.navigateTo);
      return;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const skip = () => {
      if (cancelled) return;
      if (isLast) onDoneRef.current();
      else setIndex((i) => i + 1);
    };

    const resolve = (attempt: number) => {
      if (cancelled) return;
      const el = document.querySelector(`[data-tour="${step.anchor}"]`);
      if (el instanceof HTMLElement) {
        setRect(el.getBoundingClientRect());
        return;
      }
      if (attempt < 1) {
        timer = setTimeout(() => resolve(attempt + 1), 50);
        return;
      }
      skip();
    };

    setRect(null);
    resolve(0);

    return () => {
      cancelled = true;
      if (timer !== undefined) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index, location.pathname]);

  // Keep the ring/card aligned to the anchor as the viewport moves.
  useEffect(() => {
    if (!step) return;
    const recompute = () => {
      const el = document.querySelector(`[data-tour="${step.anchor}"]`);
      if (el instanceof HTMLElement) setRect(el.getBoundingClientRect());
    };
    window.addEventListener("resize", recompute);
    window.addEventListener("scroll", recompute, true);
    return () => {
      window.removeEventListener("resize", recompute);
      window.removeEventListener("scroll", recompute, true);
    };
  }, [step]);

  if (!step) return null;

  const goBack = () => setIndex((i) => Math.max(0, i - 1));
  const goNext = () => {
    if (isLast) onDone();
    else setIndex((i) => i + 1);
  };

  // Place the card below-right of the anchor, clamped to the viewport.
  let cardTop = MARGIN;
  let cardLeft = MARGIN;
  if (rect) {
    cardTop = rect.bottom + MARGIN;
    cardLeft = rect.left;
    const maxLeft = window.innerWidth - CARD_WIDTH - MARGIN;
    if (cardLeft > maxLeft) cardLeft = Math.max(MARGIN, maxLeft);
    const maxTop = window.innerHeight - 200;
    if (cardTop > maxTop) cardTop = Math.max(MARGIN, rect.top - 200);
  }

  return (
    <Box
      role="dialog"
      aria-label="Guided tour"
      sx={{ position: "fixed", inset: 0, zIndex: 1400, pointerEvents: "none" }}
    >
      {rect && (
        <Box
          aria-hidden
          sx={{
            position: "fixed",
            top: rect.top - 4,
            left: rect.left - 4,
            width: rect.width + 8,
            height: rect.height + 8,
            borderRadius: 1,
            border: "2px solid",
            borderColor: "primary.main",
            boxShadow: "0 0 0 9999px rgba(0, 0, 0, 0.5)",
            pointerEvents: "none",
          }}
        />
      )}
      <Paper
        elevation={8}
        sx={{
          position: "fixed",
          top: cardTop,
          left: cardLeft,
          width: CARD_WIDTH,
          maxWidth: "calc(100vw - 24px)",
          p: 2,
          pointerEvents: "auto",
        }}
      >
        <Typography variant="h6" gutterBottom>
          {step.title}
        </Typography>
        <Typography variant="body2" sx={{ mb: 2 }}>
          {step.body}
        </Typography>
        <Box sx={{ display: "flex", justifyContent: "space-between", gap: 1 }}>
          <Button size="small" onClick={onDone}>
            Skip
          </Button>
          <Box sx={{ display: "flex", gap: 1 }}>
            <Button size="small" disabled={isFirst} onClick={goBack}>
              Back
            </Button>
            <Button size="small" variant="contained" onClick={goNext}>
              {isLast ? "Done" : "Next"}
            </Button>
          </Box>
        </Box>
      </Paper>
    </Box>
  );
}
