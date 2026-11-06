;; Q: can a drawing open read-only without a dialog, and can that state be read back?
(add-line)
(command "_.SAVEAS" "" (strcat *dir* "source.dwg"))
(command "_.SAVEAS" "" (strcat *dir* "other.dwg"))
(log-kv "start" (state))
(log-kv "commands"
  (mapcar (function (lambda (c) (cons c (getcname c))))
          '("OPEN" "-OPEN" "FILEOPEN" "VLA")))

(setq *docs* (vla-get-documents (vlax-get-acad-object)))
(setq *ro*
  (safe "vla-open-readonly"
    (function (lambda () (vla-open *docs* (strcat *dir* "source.dwg") :vlax-true)))))
(log-kv "after-vla-open-running" T)
(log-kv "state" (state))
(safe "docs" (function (lambda () (vla-get-count *docs*))))
(safe "active-name" (function (lambda () (vla-get-name (vla-get-activedocument (vlax-get-acad-object))))))
(safe "active-readonly" (function (lambda () (vla-get-readonly (vla-get-activedocument (vlax-get-acad-object))))))
(safe "ro-readonly" (function (lambda () (vla-get-readonly *ro*))))
(safe "writestat" (function (lambda () (getvar "WRITESTAT"))))
(safe "readonly-var" (function (lambda () (getvar "READONLY"))))

;; Edit the read-only drawing, then save to a new path.
(safe "draw" (function (lambda () (add-line) (sslength (ssget "_X")))))
(safe "saveas-copy" (function (lambda () (command "_.SAVEAS" "" (strcat *dir* "copy.dwg")) (state))))
(log-kv "copy-exists" (findfile (strcat *dir* "copy.dwg")))
(finish)
