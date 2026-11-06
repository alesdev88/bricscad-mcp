;; Q: what happens to LISP when the only open drawing is closed?
(add-line)
(command "_.SAVEAS" "" (strcat *dir* "only.dwg"))
(log-kv "about-to-close-last" (state))
(vla-close (vla-get-activedocument (vlax-get-acad-object)) :vlax-false)
(log-kv "after-close-last-still-running" T)
(safe "docs" (function (lambda () (vla-get-count (vla-get-documents (vlax-get-acad-object))))))
(finish)
