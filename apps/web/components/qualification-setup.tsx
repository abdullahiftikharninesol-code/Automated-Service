"use client";

import { FormEvent, useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";
import { label } from "@/lib/format";
import type { QualificationField, QualificationFieldType } from "@/lib/types";

const STARTER_TEMPLATES = [
  "CLOTHING",
  "DENTAL",
  "REAL_ESTATE",
  "HOME_SERVICES",
  "GENERAL",
  "SALON",
  "AGENCY",
  "RESTAURANT",
  "SAAS",
  "ECOMMERCE",
];

const FIELD_TYPES: QualificationFieldType[] = [
  "TEXT",
  "NUMBER",
  "BOOLEAN",
  "DATE",
  "DATETIME",
  "CHOICE",
  "MULTI_CHOICE",
  "PHONE",
  "EMAIL",
  "LOCATION",
];

export function QualificationSetup() {
  const [fields, setFields] = useState<QualificationField[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [selectedTemplate, setSelectedTemplate] = useState("CLOTHING");
  const [replaceExisting, setReplaceExisting] = useState(false);
  const [applyingTemplate, setApplyingTemplate] = useState(false);
  const [addingField, setAddingField] = useState(false);

  // Form state
  const [newKey, setNewKey] = useState("");
  const [newLabel, setNewLabel] = useState("");
  const [newType, setNewType] = useState<QualificationFieldType>("TEXT");
  const [newRequired, setNewRequired] = useState(true);
  const [newQuestionText, setNewQuestionText] = useState("");

  const loadFields = async () => {
    try {
      const res = await apiFetch<{ items: QualificationField[] }>("/qualification-fields");
      setFields(res.items);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load fields");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let ignore = false;
    apiFetch<{ items: QualificationField[] }>("/qualification-fields")
      .then((res) => {
        if (!ignore) setFields(res.items);
      })
      .catch((err: unknown) => {
        if (!ignore) setError(err instanceof Error ? err.message : "Failed to load fields");
      })
      .finally(() => {
        if (!ignore) setLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, []);

  async function handleApplyTemplate(e: FormEvent) {
    e.preventDefault();
    setError("");
    setMessage("");
    setApplyingTemplate(true);
    try {
      const res = await apiFetch<{ items: QualificationField[] }>(
        "/qualification-fields/apply-template",
        {
          method: "POST",
          body: JSON.stringify({
            template_name: selectedTemplate,
            replace_existing: replaceExisting,
          }),
        }
      );
      setFields(res.items);
      setMessage(`Applied ${selectedTemplate} starter template successfully.`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to apply template");
    } finally {
      setApplyingTemplate(false);
    }
  }

  async function handleAddField(e: FormEvent) {
    e.preventDefault();
    if (!newKey.trim() || !newLabel.trim()) return;
    setError("");
    setMessage("");
    setAddingField(true);
    try {
      await apiFetch<QualificationField>("/qualification-fields", {
        method: "POST",
        body: JSON.stringify({
          key: newKey.trim().toLowerCase(),
          label: newLabel.trim(),
          field_type: newType,
          required: newRequired,
          question_text: newQuestionText.trim() || null,
        }),
      });
      setNewKey("");
      setNewLabel("");
      setNewQuestionText("");
      setMessage("Qualification field added.");
      await loadFields();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to add field");
    } finally {
      setAddingField(false);
    }
  }

  async function toggleFieldRequired(field: QualificationField) {
    try {
      await apiFetch<QualificationField>(`/qualification-fields/${field.id}`, {
        method: "PATCH",
        body: JSON.stringify({ required: !field.required }),
      });
      await loadFields();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to update field");
    }
  }

  async function toggleFieldEnabled(field: QualificationField) {
    try {
      await apiFetch<QualificationField>(`/qualification-fields/${field.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !field.enabled }),
      });
      await loadFields();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to update field");
    }
  }

  async function deleteField(fieldId: string) {
    if (!confirm("Are you sure you want to delete this qualification field?")) return;
    try {
      await apiFetch(`/qualification-fields/${fieldId}`, { method: "DELETE" });
      await loadFields();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to delete field");
    }
  }

  return (
    <section className="card max-w-3xl p-5 md:p-7">
      <div className="mb-4">
        <h2 className="mb-1 font-extrabold text-slate-900">Lead Qualification Setup</h2>
        <p className="text-sm text-slate-500">
          Configure what details to extract from customer inquiries, which ones are required,
          and clarification questions to ask automatically when information is missing.
        </p>
      </div>

      {error && <div className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      {message && (
        <div className="mb-4 rounded-lg bg-emerald-50 p-3 text-sm font-semibold text-emerald-800">
          {message}
        </div>
      )}

      {/* Starter Template Toolbar */}
      <div className="mb-6 rounded-lg border border-slate-200 bg-slate-50/70 p-4">
        <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-600">
          Apply Starter Template
        </h3>
        <form onSubmit={handleApplyTemplate} className="flex flex-wrap items-center gap-3">
          <select
            className="field max-w-xs text-sm"
            value={selectedTemplate}
            onChange={(e) => setSelectedTemplate(e.target.value)}
          >
            {STARTER_TEMPLATES.map((tmpl) => (
              <option key={tmpl} value={tmpl}>
                {label(tmpl)}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
            <input
              type="checkbox"
              checked={replaceExisting}
              onChange={(e) => setReplaceExisting(e.target.checked)}
              className="rounded border-slate-300"
            />
            Replace existing
          </label>
          <button
            type="submit"
            disabled={applyingTemplate}
            className="btn btn-secondary text-xs font-bold"
          >
            {applyingTemplate ? "Applying…" : "Apply Template"}
          </button>
        </form>
      </div>

      {/* Current Fields Table */}
      <div className="mb-6">
        <h3 className="mb-3 text-xs font-bold uppercase tracking-wider text-slate-600">
          Configured Fields ({fields.length})
        </h3>
        {loading ? (
          <p className="text-sm text-slate-500">Loading fields…</p>
        ) : fields.length === 0 ? (
          <p className="rounded-lg border border-dashed border-slate-200 p-4 text-center text-sm text-slate-500">
            No qualification fields configured yet. Apply a starter template above or add custom fields below.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-xs font-bold uppercase tracking-wider text-slate-600">
                <tr>
                  <th className="p-3">Key / Label</th>
                  <th className="p-3">Type</th>
                  <th className="p-3">Required</th>
                  <th className="p-3">Question Text</th>
                  <th className="p-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {fields.map((field) => (
                  <tr key={field.id} className={field.enabled ? "" : "opacity-50"}>
                    <td className="p-3">
                      <div className="font-semibold text-slate-900">{field.label}</div>
                      <div className="font-mono text-xs text-slate-500">{field.key}</div>
                    </td>
                    <td className="p-3 text-xs font-medium text-slate-600">{field.field_type}</td>
                    <td className="p-3">
                      <button
                        type="button"
                        onClick={() => toggleFieldRequired(field)}
                        className={`rounded px-2 py-0.5 text-xs font-bold ${
                          field.required
                            ? "bg-red-50 text-red-700 ring-1 ring-red-200"
                            : "bg-slate-100 text-slate-600"
                        }`}
                      >
                        {field.required ? "Required" : "Optional"}
                      </button>
                    </td>
                    <td className="p-3 text-xs text-slate-600">
                      {field.question_text || <span className="italic text-slate-400">Auto-generated</span>}
                    </td>
                    <td className="p-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => toggleFieldEnabled(field)}
                          className="text-xs font-semibold text-slate-600 hover:text-slate-900"
                        >
                          {field.enabled ? "Disable" : "Enable"}
                        </button>
                        <button
                          type="button"
                          onClick={() => deleteField(field.id)}
                          className="text-xs font-semibold text-red-600 hover:text-red-800"
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Add Custom Field Form */}
      <div className="border-t border-slate-200 pt-5">
        <h3 className="mb-3 text-xs font-bold uppercase tracking-wider text-slate-600">
          Add Custom Field
        </h3>
        <form onSubmit={handleAddField} className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <span className="label text-xs">Field Key</span>
              <input
                type="text"
                value={newKey}
                onChange={(e) => setNewKey(e.target.value)}
                placeholder="e.g. delivery_city"
                className="field text-sm"
                required
              />
            </div>
            <div>
              <span className="label text-xs">Field Label</span>
              <input
                type="text"
                value={newLabel}
                onChange={(e) => setNewLabel(e.target.value)}
                placeholder="e.g. Delivery City"
                className="field text-sm"
                required
              />
            </div>
            <div>
              <span className="label text-xs">Field Type</span>
              <select
                value={newType}
                onChange={(e) => setNewType(e.target.value as QualificationFieldType)}
                className="field text-sm"
              >
                {FIELD_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <span className="label text-xs">Custom Clarification Question (Optional)</span>
            <input
              type="text"
              value={newQuestionText}
              onChange={(e) => setNewQuestionText(e.target.value)}
              placeholder="e.g. Which city should we deliver to?"
              className="field text-sm"
            />
          </div>
          <div className="flex items-center justify-between pt-1">
            <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
              <input
                type="checkbox"
                checked={newRequired}
                onChange={(e) => setNewRequired(e.target.checked)}
                className="rounded border-slate-300"
              />
              Required for qualification
            </label>
            <button
              type="submit"
              disabled={addingField || !newKey.trim() || !newLabel.trim()}
              className="btn btn-secondary text-xs font-bold"
            >
              {addingField ? "Adding…" : "Add Field"}
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}
