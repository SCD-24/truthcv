import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import InputAdornment from "@mui/material/InputAdornment";
import TextField from "@mui/material/TextField";
import Autocomplete from "@mui/material/Autocomplete";
import type { AutocompleteChangeReason } from "@mui/material/Autocomplete";
import { ButtonSpinner } from "../components/ButtonSpinner";
import type { ModelInfo } from "../api/types";
import { useMemo } from "react";
import type { SyntheticEvent } from "react";

/** Sentinel select value that reveals the free-text model field. Mirrors the
 * pattern the old provider panel used for its model field. */
export const CUSTOM_MODEL = "__custom__";

interface ModelOption {
  value: string;
  label: string;
}

/** Case-insensitive substring match against both the option's label and its
 * model id, keeping "Provider default" and "Custom…" always available so
 * they never scroll out of reach behind a search that matches no model. */
function filterModelOptions(options: ModelOption[], inputValue: string): ModelOption[] {
  const query = inputValue.trim().toLowerCase();
  if (!query) return options;
  return options.filter(
    (o) =>
      o.value === "" ||
      o.value === CUSTOM_MODEL ||
      o.label.toLowerCase().includes(query) ||
      o.value.toLowerCase().includes(query),
  );
}

/** Searchable model picker: an Autocomplete over the connection's live model
 * list (plus "Provider default" and "Custom…"), with a Reload button merged
 * into its input adornment and, when Custom is chosen, a free-text field for
 * an exact model id not in the list. */
export function ModelSelect({
  models,
  model,
  customModel,
  onChange,
  onReload,
  modelsLoading,
  modelsError,
  connection,
}: {
  models: ModelInfo[];
  model: string;
  customModel: boolean;
  onChange: (next: { model: string; customModel: boolean }) => void;
  onReload: () => void;
  modelsLoading: boolean;
  modelsError: string | null;
  connection: string;
}) {
  // Memoised so the option objects keep a stable identity across parent
  // re-renders: Autocomplete resets the typed search text whenever the
  // controlled `value` changes identity, even while the input is focused.
  const options: ModelOption[] = useMemo(
    () => [
      { value: "", label: "Provider default" },
      ...models.map((m) => ({ value: m.id, label: m.label })),
      { value: CUSTOM_MODEL, label: "Custom…" },
    ],
    [models],
  );
  const value =
    options.find((o) => o.value === (customModel ? CUSTOM_MODEL : model)) ?? options[0];

  function handleChange(
    _event: SyntheticEvent,
    option: ModelOption | null,
    _reason: AutocompleteChangeReason,
  ) {
    if (!option) return;
    if (option.value === CUSTOM_MODEL) {
      onChange({ model: "", customModel: true });
    } else {
      onChange({ model: option.value, customModel: false });
    }
  }

  const reloadButton = (
    <InputAdornment position="end" sx={{ mr: 2 }}>
      <Button size="small" onClick={onReload} disabled={modelsLoading || !connection}>
        {modelsLoading && <ButtonSpinner size={12} />}
        {modelsLoading ? "Loading…" : "Reload"}
      </Button>
    </InputAdornment>
  );

  return (
    <Box>
      <Autocomplete
        disableClearable
        fullWidth
        options={options}
        value={value}
        onChange={handleChange}
        isOptionEqualToValue={(option, val) => option.value === val.value}
        getOptionLabel={(option) => option.label}
        filterOptions={(opts, state) => filterModelOptions(opts, state.inputValue)}
        renderInput={(params) => (
          <TextField
            {...params}
            label="Model"
            helperText={
              modelsError
                ? `${modelsError} You can still pick Custom or reload.`
                : "Pulled live from the connection. Blank uses its default; choose Custom for an id not listed."
            }
            slotProps={{
              ...params.slotProps,
              input: {
                ...params.slotProps.input,
                endAdornment: (
                  <>
                    {reloadButton}
                    {params.slotProps.input.endAdornment}
                  </>
                ),
              },
            }}
          />
        )}
      />
      {customModel && (
        <TextField
          fullWidth
          type="text"
          value={model}
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus
          onChange={(e) => onChange({ model: e.target.value, customModel: true })}
          placeholder="Exact model id"
          slotProps={{ htmlInput: { "aria-label": "Custom model id" } }}
          sx={{ mt: 1.5 }}
        />
      )}
    </Box>
  );
}
