import CircularProgress from "@mui/material/CircularProgress";
import Box from "@mui/material/Box";

interface ButtonSpinnerProps {
  /** Size of the spinner in pixels. Default: 16. */
  size?: number;
  /** Color of the spinner. Default: "inherit" (inherits button text color). */
  color?: string;
}

/**
 * Reusable spinner glyph for inline button use. Rendered before the label text
 * when an async operation is in flight. Sized for horizontal layout within a
 * button's label area.
 */
export function ButtonSpinner({ size = 16, color = "inherit" }: ButtonSpinnerProps) {
  return (
    <Box
      component="span"
      sx={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        marginRight: 1,
      }}
    >
      <CircularProgress
        size={size}
        thickness={5}
        sx={{
          color: color === "inherit" ? "currentColor" : color,
        }}
      />
    </Box>
  );
}
