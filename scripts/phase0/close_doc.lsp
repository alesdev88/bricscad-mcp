;; Q: can a document be closed without stopping LISP or opening a dialog?
(add-line)
(command "_.SAVEAS" "" (strcat *dir* "first.dwg"))
(add-line)
(command "_.SAVEAS" "" (strcat *dir* "second.dwg"))
(command "_.OPEN" (strcat *dir* "first.dwg"))
(log-kv "two-open" (list (state) (vla-get-count (vla-get-documents (vlax-get-acad-object)))))

;; Close the active, unmodified document.
(safe "close-unmodified" (function (lambda () (command "_.CLOSE") (state))))
(log-kv "after-close-unmodified-running" T)
(log-kv "state" (state))
(safe "docs" (function (lambda () (vla-get-count (vla-get-documents (vlax-get-acad-object))))))
(safe "can-draw" (function (lambda () (add-line) (sslength (ssget "_X")))))

;; The active document is now modified; close it and discard.
(safe "close-modified" (function (lambda () (command "_.CLOSE" "_Y") (state))))
(log-kv "after-close-modified-running" T)
(log-kv "state2" (state))
(safe "docs2" (function (lambda () (vla-get-count (vla-get-documents (vlax-get-acad-object))))))
(finish)
