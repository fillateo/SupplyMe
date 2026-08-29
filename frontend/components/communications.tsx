"use client";

import { useState } from "react";

import type { Call, Thread } from "@/lib/types";
import { StatusChip } from "./primitives";

export function Communications({
  data,
}: {
  data: {
    email: { sent: number; responded: number; awaiting: number; threads: Thread[] };
    calls: {
      completed: number; scheduled: number; failed: number;
      not_attempted: number; items: Call[];
    };
  };
}) {
  const [open, setOpen] = useState<string | null>(null);

  return (
    <div className="space-y-8">
      <section>
        <div className="mb-3 flex items-baseline gap-6">
          <h3 className="col-label">Email</h3>
          <p className="font-mono text-2xs uppercase tracking-[0.08em] text-muted">
            {data.email.sent} sent · {data.email.responded} replied · {data.email.awaiting} waiting
          </p>
        </div>
        {data.email.threads.length === 0 ? (
          <p className="py-4 text-sm text-muted">Nothing sent yet.</p>
        ) : (
          <ul className="space-y-2">
            {data.email.threads.map((thread) => (
              <li key={thread.id} className="card overflow-hidden">
                <button
                  onClick={() => setOpen(open === thread.id ? null : thread.id)}
                  className="flex w-full items-start justify-between gap-4 px-5 py-3.5 text-left hover:bg-paper/50"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm text-ink">{thread.vendor_name}</p>
                    <p className="mt-0.5 truncate font-mono text-2xs text-faint">
                      {thread.to_address} · {thread.answered.length}/{thread.asked.length} questions
                      answered
                      {thread.follow_up_count > 0 && ` · ${thread.follow_up_count} follow-up`}
                    </p>
                  </div>
                  <StatusChip status={thread.status} />
                </button>

                {open === thread.id && (
                  <div className="space-y-3 border-t border-rule px-5 py-4">
                    {thread.messages.map((message) => (
                      <div key={message.id}>
                        <p className="col-label">
                          {message.direction === "outbound" ? "We asked" : "They replied"}
                        </p>
                        <pre className="mt-1.5 whitespace-pre-wrap rounded-sm bg-paper/60 px-3 py-2.5 font-mono text-xs leading-relaxed text-ink">
                          {message.body}
                        </pre>
                      </div>
                    ))}
                    {thread.commitments.length > 0 && (
                      <div>
                        <p className="col-label">What they committed to</p>
                        <ul className="mt-1 space-y-0.5">
                          {thread.commitments.map((commitment, index) => (
                            <li key={index} className="font-mono text-xs text-ink">
                              {commitment}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {thread.unanswered.length > 0 && (
                      <div>
                        <p className="col-label">Still unanswered</p>
                        <ul className="mt-1 space-y-0.5">
                          {thread.unanswered.map((question, index) => (
                            <li key={index} className="text-xs text-muted">
                              {question}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <div className="mb-3 flex items-baseline gap-6">
          <h3 className="col-label">Calls</h3>
          <p className="font-mono text-2xs uppercase tracking-[0.08em] text-muted">
            {data.calls.completed} completed · {data.calls.scheduled} queued ·{" "}
            {data.calls.failed} failed
            {data.calls.not_attempted > 0 &&
              ` · ${data.calls.not_attempted} skipped, budget spent elsewhere`}
          </p>
        </div>
        {data.calls.items.length === 0 ? (
          <p className="py-4 text-sm text-muted">
            No calls. It only dials when writing will not settle a question.
          </p>
        ) : (
          <ul className="space-y-2">
            {data.calls.items.map((call) => (
              <li key={call.id} className="card overflow-hidden">
                <button
                  onClick={() => setOpen(open === call.id ? null : call.id)}
                  className="flex w-full items-start justify-between gap-4 px-5 py-3.5 text-left hover:bg-paper/50"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm text-ink">{call.vendor_name}</p>
                    <p className="mt-0.5 truncate text-xs text-muted">
                      Called because {call.reason}
                    </p>
                  </div>
                  <StatusChip status={call.status} />
                </button>

                {open === call.id && call.transcript.length > 0 && (
                  <div className="space-y-2 border-t border-rule px-5 py-4">
                    {call.transcript.map((turn, index) => (
                      <p key={index} className="text-xs leading-relaxed">
                        <span className="col-label mr-2">
                          {turn.speaker === "agent" ? "AI" : "Supplier"}
                        </span>
                        <span className={turn.speaker === "agent" ? "text-muted" : "text-ink"}>
                          {turn.text}
                        </span>
                      </p>
                    ))}
                    {call.unanswered_questions.length > 0 && (
                      <p className="pt-2 text-xs text-muted">
                        <span className="col-label mr-2">Not answered</span>
                        {call.unanswered_questions.join("; ")}
                      </p>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
