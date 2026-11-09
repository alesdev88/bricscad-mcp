;; Drawing and editing. Relies on the helpers in read.lsp.

;; Every edit runs through here: one undo step on success, no change at all on failure.
;; Only marks work. _.UNDO with a count undoes the listener's own _.DELAY instead.
(defun mcp:edit (worker args / result message)
  (command "_.UNDO" "_Mark")
  (setq *mcp-pending-error* nil
        result (vl-catch-all-apply worker args))
  (if (vl-catch-all-error-p result)
    (progn
      (setq message (cond (*mcp-pending-error*) ((vl-catch-all-error-message result))))
      (mcp:cancel-command)
      (command "_.UNDO" "_Back")
      (setq *mcp-pending-error* message)
      (exit)
    )
  )
  result
)

;; _Back prompts only when no mark is left, and answering No keeps the drawing as it is.
(defun mcp:undo (steps / undone remaining)
  (setq undone 0 remaining steps)
  (while (> remaining 0)
    (command "_.UNDO" "_Back")
    (if (> (getvar "CMDACTIVE") 0)
      (progn
        (command "_N")
        (setq remaining 0)
      )
      (setq undone (1+ undone)
            remaining (1- remaining))
    )
  )
  (mcp:obj (list (cons "undone" undone) (cons "requested" steps)))
)
