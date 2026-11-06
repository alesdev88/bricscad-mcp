;; Q: how can a modified drawing be closed without a dialog, with another still open?
(add-line)
(command "_.SAVEAS" "" (strcat *dir* "first.dwg"))
(command "_.SAVEAS" "" (strcat *dir* "second.dwg"))
(setq *docs* (vla-get-documents (vlax-get-acad-object)))
(vla-open *docs* (strcat *dir* "first.dwg") :vlax-false)
(log-kv "open-count" (list (state) (vla-get-count *docs*)))
(add-line)
(log-kv "modified" (state))

;; A: COM close without saving.
(safe "vla-close-no-save"
  (function (lambda ()
    (vla-close (vla-get-activedocument (vlax-get-acad-object)) :vlax-false)
    (state))))
(log-kv "after-vla-close-running" T)
(log-kv "state-a" (state))
(safe "docs-a" (function (lambda () (vla-get-count *docs*))))

;; B: reopen, modify, then the command. Logged before it runs, so a hang is visible.
(vla-open *docs* (strcat *dir* "first.dwg") :vlax-false)
(add-line)
(log-kv "about-to-run-command-close" (state))
(command "_.CLOSE")
(log-kv "after-command-close" (state))
(if (> (getvar "CMDACTIVE") 0)
  (progn (log-kv "prompted-for" (getvar "LASTPROMPT")) (command "_Y") (log-kv "after-y" (state)))
)
(log-kv "docs-b" (vla-get-count *docs*))
(finish)
