import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Alert from "@mui/material/Alert";
import Typography from "@mui/material/Typography";
import { useWizard } from "../wizard/store";
import { getTruth, saveTruth } from "../api/client";
import type {
  Bullet,
  Education,
  Experience,
  Hobby,
  Profile,
  Skill,
  TruthDoc,
  TruthSource,
} from "../api/types";
import "../styles/step.css";

// Every fact is stamped with where it came from — attested from the uploaded
// CV, or a fact the user is standing behind (edits and additions).
function Stamp({ source }: { source: TruthSource }) {
  return (
    <span className="stamp stamp--attested">
      {source === "user-confirmed" ? "Confirmed · you" : "Attested · CV"}
    </span>
  );
}

const isEmpty = (t: TruthDoc) =>
  t.experiences.length === 0 && t.education.length === 0 && t.skills.length === 0 && t.hobbies.length === 0;

let seq = 0;
const newId = (p: string) => `${p}-new-${Date.now().toString(36)}-${seq++}`;

export interface ReviewStepProps {
  onNext: () => void;
  onBack?: () => void;
  /**
   * Header overline text (e.g. "Step 2 of 2"). Defaults to "Step 2 of 2".
   */
  eyebrow?: string;
  /**
   * Main header title (e.g. "Review what we found"). Defaults to "Review what we found".
   */
  title?: string;
  /**
   * Leading paragraph text. Defaults to the standard onboarding lede about CV facts.
   */
  lede?: string;
  /**
   * Primary button label (e.g. "Save & continue"). Defaults to "Save & continue".
   */
  nextLabel?: string;
  /**
   * Back button label (e.g. "Back"). Defaults to "Back". Only rendered if onBack is defined.
   */
  backLabel?: string;
}

export function ReviewStep({
  onNext,
  onBack,
  eyebrow = "Step 2 of 2",
  title = "Review what we found",
  lede,
  nextLabel = "Save & continue",
  backLabel = "Back",
}: ReviewStepProps) {
  const { truth, setTruth, run, loading, error } = useWizard();
  const [doc, setDoc] = useState<TruthDoc>(truth);
  const defaultLede =
    "Each job keeps its own dates and highlights, so nothing drifts between " +
    "roles. Correct anything wrong — once you save, these are the facts we " +
    "stand behind.";
  const displayLede = lede ?? defaultLede;

  // Load the truth file on first visit if the store has none yet.
  useEffect(() => {
    if (isEmpty(truth)) {
      run(async () => {
        const loaded = await getTruth();
        setTruth(loaded);
        setDoc({ ...loaded, hobbies: loaded.hobbies ?? [] });
        return true;
      });
    } else {
      setDoc({ ...truth, hobbies: truth.hobbies ?? [] });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- immutable edit helpers -------------------------------------------
  const patchExp = (id: string, patch: Partial<Experience>) =>
    setDoc((d) => ({
      ...d,
      experiences: d.experiences.map((e) => (e.id === id ? { ...e, ...patch } : e)),
    }));
  const removeExp = (id: string) =>
    setDoc((d) => ({ ...d, experiences: d.experiences.filter((e) => e.id !== id) }));
  const addExp = () =>
    setDoc((d) => ({
      ...d,
      experiences: [
        ...d.experiences,
        { id: newId("exp"), role: "", company: "", start: "", end: "", source: "user-confirmed", bullets: [] },
      ],
    }));

  const patchProfile = (patch: Partial<Profile>) =>
    setDoc((d) => ({ ...d, profile: { ...d.profile, ...patch } }));
  const patchLink = (i: number, patch: Partial<Profile["links"][number]>) =>
    setDoc((d) => ({
      ...d,
      profile: {
        ...d.profile,
        links: d.profile.links.map((l, j) => (j === i ? { ...l, ...patch } : l)),
      },
    }));
  const addLink = () =>
    setDoc((d) => ({
      ...d,
      profile: { ...d.profile, links: [...d.profile.links, { label: "", url: "" }] },
    }));
  const removeLink = (i: number) =>
    setDoc((d) => ({
      ...d,
      profile: { ...d.profile, links: d.profile.links.filter((_, j) => j !== i) },
    }));

  const patchBullet = (expId: string, bId: string, value: string) =>
    setDoc((d) => ({
      ...d,
      experiences: d.experiences.map((e) =>
        e.id === expId
          ? { ...e, bullets: e.bullets.map((b) => (b.id === bId ? { ...b, value } : b)) }
          : e,
      ),
    }));
  const removeBullet = (expId: string, bId: string) =>
    setDoc((d) => ({
      ...d,
      experiences: d.experiences.map((e) =>
        e.id === expId ? { ...e, bullets: e.bullets.filter((b) => b.id !== bId) } : e,
      ),
    }));
  const addBullet = (expId: string) =>
    setDoc((d) => ({
      ...d,
      experiences: d.experiences.map((e) =>
        e.id === expId
          ? { ...e, bullets: [...e.bullets, { id: newId("b"), value: "", source: "user-confirmed" as TruthSource }] }
          : e,
      ),
    }));

  const patchEdu = (id: string, patch: Partial<Education>) =>
    setDoc((d) => ({
      ...d,
      education: d.education.map((e) => (e.id === id ? { ...e, ...patch } : e)),
    }));
  const removeEdu = (id: string) =>
    setDoc((d) => ({ ...d, education: d.education.filter((e) => e.id !== id) }));
  const addEdu = () =>
    setDoc((d) => ({
      ...d,
      education: [
        ...d.education,
        { id: newId("edu"), degree: "", school: "", start: "", end: "", source: "user-confirmed" },
      ],
    }));

  const patchSkill = (id: string, value: string) =>
    setDoc((d) => ({
      ...d,
      skills: d.skills.map((s) => (s.id === id ? { ...s, value } : s)),
    }));
  const removeSkill = (id: string) =>
    setDoc((d) => ({ ...d, skills: d.skills.filter((s) => s.id !== id) }));
  const addSkill = () =>
    setDoc((d) => ({
      ...d,
      skills: [...d.skills, { id: newId("sk"), value: "", source: "user-confirmed" }],
    }));

  const patchHobby = (id: string, value: string) =>
    setDoc((d) => ({
      ...d,
      hobbies: d.hobbies.map((h) => (h.id === id ? { ...h, value } : h)),
    }));
  const removeHobby = (id: string) =>
    setDoc((d) => ({ ...d, hobbies: d.hobbies.filter((h) => h.id !== id) }));
  const addHobby = () =>
    setDoc((d) => ({
      ...d,
      hobbies: [...d.hobbies, { id: newId("hb"), value: "", source: "user-confirmed" }],
    }));

  // ---- save: drop empties, persist ---------------------------------------
  const save = async () => {
    const cleaned: TruthDoc = {
      experiences: doc.experiences
        .map((e) => ({ ...e, bullets: e.bullets.filter((b) => b.value.trim()) }))
        .filter((e) => e.role.trim() || e.company.trim() || e.bullets.length),
      education: doc.education.filter((e) => e.degree.trim() || e.school.trim()),
      skills: doc.skills.filter((s) => s.value.trim()),
      hobbies: doc.hobbies.filter((h) => h.value.trim()),
      profile: {
        ...doc.profile,
        links: doc.profile.links.filter((l) => l.label.trim() || l.url.trim()),
      },
    };
    const ok = await run(async () => {
      await saveTruth(cleaned);
      setTruth(cleaned);
      return true;
    });
    if (ok) onNext();
  };

  return (
    <section>
      <div className="stage__head">
        <Typography variant="overline" className="eyebrow">{eyebrow}</Typography>
        <h1 className="stage__title">{title}</h1>
        <p className="stage__lede">{displayLede}</p>
      </div>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}
      {loading && isEmpty(doc) && (
        <Typography variant="body2" className="busy" sx={{ color: "text.secondary" }}>
          Reading your truth file…
        </Typography>
      )}

      <div className="ledger">
        <section className="group">
          <header className="group__head">
            <h2 className="group__title">Profile</h2>
          </header>
          <article className="exp">
            <div className="exp__grid">
              <Field
                label="Name"
                value={doc.profile.name}
                onChange={(v) => patchProfile({ name: v })}
              />
              <Field
                label="Location"
                value={doc.profile.location}
                onChange={(v) => patchProfile({ location: v })}
              />
              <Field
                label="Email"
                value={doc.profile.email}
                onChange={(v) => patchProfile({ email: v })}
              />
              <Field
                label="Phone"
                value={doc.profile.phone}
                onChange={(v) => patchProfile({ phone: v })}
              />
            </div>

            <div className="exp__bullets">
              <span className="field__label">Links</span>
              {doc.profile.links.map((link, i) => (
                <div className="link-row" key={i}>
                  <input
                    className="input link-row__label"
                    placeholder="Label (e.g. LinkedIn)"
                    value={link.label}
                    onChange={(e) => patchLink(i, { label: e.target.value })}
                  />
                  <input
                    className="input"
                    placeholder="https://…"
                    value={link.url}
                    onChange={(e) => patchLink(i, { url: e.target.value })}
                  />
                  <button
                    type="button"
                    className="entry__remove"
                    onClick={() => removeLink(i)}
                  >
                    Remove
                  </button>
                </div>
              ))}
              <Button type="button" variant="outlined" size="small" onClick={addLink}>
                Add link
              </Button>
            </div>

            {/* The summary is the one profile field held to the truthfulness
                guardrail — set apart so its different rules read at a glance. */}
            <label className="field field--summary">
              <span className="field__label">Summary</span>
              <textarea
                className="input field__textarea"
                rows={3}
                value={doc.profile.summary}
                onChange={(e) => patchProfile({ summary: e.target.value })}
              />
              <span className="field__hint">
                Your name and contact details are yours to set freely. The summary
                is a claim — it's checked against your truth file when you render,
                so keep it to what your experience already backs up.
              </span>
            </label>
          </article>
        </section>

        <section className="group">
          <header className="group__head">
            <h2 className="group__title">Experience</h2>
            <span className="group__count">{doc.experiences.length}</span>
          </header>
          {doc.experiences.map((e) => (
            <article className="exp" key={e.id}>
              <div className="exp__head">
                <Stamp source={e.source} />
                <button type="button" className="entry__remove" onClick={() => removeExp(e.id)}>
                  Remove job
                </button>
              </div>
              <div className="exp__grid">
                <Field label="Role" value={e.role} onChange={(v) => patchExp(e.id, { role: v })} />
                <Field label="Company" value={e.company} onChange={(v) => patchExp(e.id, { company: v })} />
                <Field label="Start" value={e.start} onChange={(v) => patchExp(e.id, { start: v })} />
                <Field label="End" value={e.end} onChange={(v) => patchExp(e.id, { end: v })} />
              </div>
              <div className="exp__bullets">
                <span className="field__label">Highlights</span>
                {e.bullets.map((b: Bullet) => (
                  <div className="bullet-row" key={b.id}>
                    <Stamp source={b.source} />
                    <input
                      className="input"
                      value={b.value}
                      aria-label="Highlight"
                      onChange={(ev) => patchBullet(e.id, b.id, ev.target.value)}
                    />
                    <button type="button" className="entry__remove" onClick={() => removeBullet(e.id, b.id)}>
                      Remove
                    </button>
                  </div>
                ))}
                <button type="button" className="mini-btn" onClick={() => addBullet(e.id)}>
                  + Add highlight
                </button>
              </div>
            </article>
          ))}
          <button type="button" className="mini-btn" onClick={addExp}>
            + Add experience
          </button>
        </section>

        <section className="group">
          <header className="group__head">
            <h2 className="group__title">Education</h2>
            <span className="group__count">{doc.education.length}</span>
          </header>
          {doc.education.map((e: Education) => (
            <article className="exp" key={e.id}>
              <div className="exp__head">
                <Stamp source={e.source} />
                <button type="button" className="entry__remove" onClick={() => removeEdu(e.id)}>
                  Remove
                </button>
              </div>
              <div className="exp__grid">
                <Field label="Degree" value={e.degree} onChange={(v) => patchEdu(e.id, { degree: v })} />
                <Field label="School" value={e.school} onChange={(v) => patchEdu(e.id, { school: v })} />
                <Field label="Start" value={e.start} onChange={(v) => patchEdu(e.id, { start: v })} />
                <Field label="End" value={e.end} onChange={(v) => patchEdu(e.id, { end: v })} />
              </div>
            </article>
          ))}
          <button type="button" className="mini-btn" onClick={addEdu}>
            + Add education
          </button>
        </section>

        <section className="group">
          <header className="group__head">
            <h2 className="group__title">Skills</h2>
            <span className="group__count">{doc.skills.length}</span>
          </header>
          <div className="skills-edit">
            {doc.skills.map((s: Skill) => (
              <div className="skill-row" key={s.id}>
                <input
                  className="input"
                  value={s.value}
                  aria-label="Skill"
                  onChange={(ev) => patchSkill(s.id, ev.target.value)}
                />
                <button type="button" className="entry__remove" onClick={() => removeSkill(s.id)}>
                  ×
                </button>
              </div>
            ))}
          </div>
          <button type="button" className="mini-btn" onClick={addSkill}>
            + Add skill
          </button>
        </section>

        <section className="group">
          <header className="group__head">
            <h2 className="group__title">Hobbies</h2>
            <span className="group__count">{doc.hobbies.length}</span>
          </header>
          <div className="skills-edit">
            {(doc.hobbies ?? []).map((h: Hobby) => (
              <div className="skill-row" key={h.id}>
                <input
                  className="input"
                  value={h.value}
                  aria-label="Hobby"
                  onChange={(ev) => patchHobby(h.id, ev.target.value)}
                />
                <button type="button" className="entry__remove" onClick={() => removeHobby(h.id)}>
                  ×
                </button>
              </div>
            ))}
          </div>
          <button type="button" className="mini-btn" onClick={addHobby}>
            + Add hobby
          </button>
        </section>
      </div>

      <Box className="stage__actions" sx={{ display: "flex", gap: 2 }}>
        {onBack && (
          <Button variant="outlined" onClick={() => onBack?.()}>
            {backLabel}
          </Button>
        )}
        <Button variant="contained" disabled={loading} onClick={save}>
          {nextLabel}
        </Button>
      </Box>
    </section>
  );
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="field">
      <span className="field__label">{label}</span>
      <input className="input" value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}
