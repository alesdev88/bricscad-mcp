;; Batch jobs: one request per file. Relies on read.lsp, edit.lsp and export.lsp.

;; Opens the file read-only, runs one worker in it, and always closes it without saving.
;; A damaged file fails vla-open with E_FAIL and no dialog. Another drawing stays open, so
;; closing this one never stops the listener.
(defun mcp:batch-file (path worker args / document result message)
  (if (not (wcmatch worker "mcp:*")) (mcp:fail (strcat worker " is not a batch worker.")))
  (setq document (vl-catch-all-apply 'vla-open (list (mcp:documents) path :vlax-true)))
  (if (vl-catch-all-error-p document)
    (mcp:fail (strcat "BricsCAD could not open " path ": " (vl-catch-all-error-message document)))
  )
  (setq *mcp-pending-error* nil
        result (vl-catch-all-apply (read worker) args))
  (if (vl-catch-all-error-p result)
    (setq message (cond (*mcp-pending-error*) ((vl-catch-all-error-message result))))
  )
  (mcp:cancel-command)
  (vl-catch-all-apply 'vla-close (list document :vlax-false))
  (if message
    (progn
      (setq *mcp-pending-error* message)
      (exit)
    )
  )
  result
)
