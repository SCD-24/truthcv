import { useId, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";

/** Collapsible list of a run's per-item failure texts, shown in full. */
export function RunItemErrors({ errors }: { errors: string[] }) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  if (errors.length === 0) return null;
  return (
    <Box sx={{ px: 1.5, pb: 1 }}>
      <Button
        size="small"
        color="warning"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        onClick={() => setOpen((o) => !o)}
      >
        Failed items ({errors.length})
      </Button>
      {open && (
        <Box component="ul" id={listId} sx={{ m: 0, pl: 3 }}>
          {errors.map((err, i) => (
            <Typography
              key={i}
              component="li"
              variant="caption"
              sx={{ fontFamily: "monospace", wordBreak: "break-word", overflowWrap: "anywhere" }}
            >
              {err}
            </Typography>
          ))}
        </Box>
      )}
    </Box>
  );
}
