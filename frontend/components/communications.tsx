"use client";

import { useState } from "react";

import type { Thread } from "@/lib/types";
import { StatusChip } from "./primitives";

/*
 * Communications Hub: Clean email outreach feed with
 * delivery tracking, verified vendor responses, and commitment summaries.
 */

export function Communications({
  data,
  live = false,
}: {
  data: { email: { sent: number; responded: number; awaiting: number; threads: Thread[] } };
  live?: boolean;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const { sent, responded, awaiting, threads } = data.email;

  const responseRate = sent > 0 ? Math.round((responded / sent) * 100) : 0;

  return (
    <section className="space-y-6">
      {/* Telemetry Metrics Bar */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="card p-4 bg-white">
          <dt className="text-xs font-medium text-slate-500">Total Inquiries Sent</dt>
          <dd className="mt-1 text-2xl font-bold text-slate-900 font-mono">{sent}</dd>
        </div>
        <div className="card p-4 bg-white border-slate-200">
          <dt className="text-xs font-medium text-emerald-700">Replies Received</dt>
          <dd className="mt-1 text-2xl font-bold text-emerald-700 font-mono">{responded}</dd>
        </div>
        <div className="card p-4 bg-white border-slate-200">
          <dt className="text-xs font-medium text-amber-700">Awaiting Response</dt>
          <dd className="mt-1 text-2xl font-bold text-amber-700 font-mono">{awaiting}</dd>
        </div>
        <div className="card p-4 bg-white border-slate-200">
          <dt className="text-xs font-medium text-blue-700">Response Rate</dt>
          <dd className="mt-1 text-2xl font-bold text-blue-700 font-mono">{responseRate}%</dd>
        </div>
      </div>

      {/* Threads Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between border-b border-slate-200 pb-3">
          <h2 className="text-base font-semibold text-slate-900">
            Outreach Threads ({threads.length})
          </h2>
          <span className="text-xs text-slate-500">
            Automated negotiations and quotation inquiries
          </span>
        </div>

        {threads.length === 0 ? (
          <div className="card p-12 text-center border-dashed bg-white">
            <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-amber-50 text-amber-600 font-bold">
              ✉
            </div>
            <p className="text-base font-semibold text-slate-800">No Supplier Outreach Dispatched</p>
            <p className="mx-auto mt-1.5 max-w-md text-xs leading-relaxed text-slate-500">
              {live
                ? "The agent automatically drafts customized quotation requests as soon as candidates are qualified."
                : "This mission concluded without initiating supplier communications."}
            </p>
          </div>
        ) : (
          <ul className="space-y-3">
            {threads.map((thread) => {
              const isOpen = open === thread.id;
              const answeredCount = thread.answered.length;
              const askedCount = thread.asked.length;
              const isSettled = answeredCount === askedCount && askedCount > 0;

              return (
                <li
                  key={thread.id}
                  className={`card overflow-hidden transition-all duration-200 ${
                    isOpen ? "border-slate-300 shadow-md bg-white" : "hover:border-slate-300 bg-white"
                  }`}
                >
                  <button
                    onClick={() => setOpen(isOpen ? null : thread.id)}
                    aria-expanded={isOpen}
                    className="flex w-full items-start justify-between gap-4 p-4 text-left transition-colors hover:bg-slate-50/80 sm:p-5"
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2.5">
                        <span className="text-base font-semibold text-slate-900">
                          {thread.vendor_name}
                        </span>
                        <span className="font-mono text-xs text-slate-400">
                          &lt;{thread.to_address}&gt;
                        </span>
                      </div>

                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                        <span
                          className={`font-semibold ${
                            isSettled ? "text-emerald-700" : "text-amber-700"
                          }`}
                        >
                          {answeredCount} of {askedCount} questions answered
                        </span>
                        {thread.follow_up_count > 0 && (
                          <>
                            <span className="text-slate-300">·</span>
                            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-medium text-slate-600 border border-slate-200">
                              {thread.follow_up_count} follow-up{thread.follow_up_count === 1 ? "" : "s"}
                            </span>
                          </>
                        )}
                      </div>
                    </div>

                    <div className="flex shrink-0 items-center gap-2">
                      <StatusChip status={thread.status} />
                      <span
                        className={`text-slate-400 transition-transform duration-200 text-xs ${
                          isOpen ? "rotate-180 text-slate-700" : ""
                        }`}
                        aria-hidden
                      >
                        ▼
                      </span>
                    </div>
                  </button>

                  {isOpen && (
                    <div className="animate-rise-in space-y-5 border-t border-slate-200 bg-white p-5 sm:p-6">
                      {/* Message History Feed */}
                      <ol className="space-y-3">
                        {thread.messages.map((message) => {
                          const outbound = message.direction === "outbound";
                          return (
                            <li
                              key={message.id}
                              className={`rounded-xl border p-4 shadow-subtle transition-all ${
                                outbound
                                  ? "border-slate-200 bg-slate-50 ml-0 mr-6 sm:mr-10"
                                  : "border-emerald-200 bg-emerald-50/50 ml-6 mr-0 sm:ml-10"
                              }`}
                            >
                              <div className="flex items-center justify-between pb-2 mb-2 border-b border-slate-200/60">
                                <span
                                  className={`text-xs font-semibold ${
                                    outbound ? "text-blue-700" : "text-emerald-700"
                                  }`}
                                >
                                  {outbound ? "↗ Outbound Inquiry (Agent)" : "↙ Inbound Reply (Supplier)"}
                                </span>
                                <span className="font-mono text-xs text-slate-400">
                                  #{message.id.slice(-6)}
                                </span>
                              </div>
                              <pre className="whitespace-pre-wrap font-sans text-xs leading-relaxed text-slate-800">
                                {message.body}
                              </pre>
                            </li>
                          );
                        })}
                      </ol>

                      {/* Commitments & Extracted Terms */}
                      {thread.commitments.length > 0 && (
                        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 space-y-1.5">
                          <p className="text-xs font-semibold text-emerald-800">
                            ✓ Extracted Supplier Commitments
                          </p>
                          <ul className="space-y-1">
                            {thread.commitments.map((commitment, index) => (
                              <li
                                key={index}
                                className="flex items-start gap-2 text-xs text-emerald-900"
                              >
                                <span className="text-emerald-600 font-bold">✓</span>
                                <span>{commitment}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Unanswered Questions */}
                      {thread.unanswered.length > 0 && (
                        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 space-y-1.5">
                          <p className="text-xs font-semibold text-amber-800">
                            ⚠ Pending Questions Awaiting Answer
                          </p>
                          <ul className="space-y-1">
                            {thread.unanswered.map((question, index) => (
                              <li
                                key={index}
                                className="flex items-start gap-2 text-xs text-amber-900"
                              >
                                <span className="text-amber-600 font-bold">?</span>
                                <span>{question}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}


