;; Q: does opening another drawing stop LISP running in the first document?
(log-kv "filedia" (getvar "FILEDIA"))
(log-kv "sdi" (getvar "SDI"))
(log-kv "lispinit" (getvar "LISPINIT"))
(add-line)
(command "_.SAVEAS" "" (strcat *dir* "first.dwg"))
(log-kv "after-saveas-first" (state))
(add-line)
(add-line)
(command "_.SAVEAS" "" (strcat *dir* "second.dwg"))
(log-kv "after-saveas-second" (state))
(log-kv "entities-in-second" (sslength (ssget "_X")))

;; Reopen the first drawing; it holds one line, the second holds three.
(safe "command-open" (function (lambda () (command "_.OPEN" (strcat *dir* "first.dwg")) (state))))
(log-kv "after-open-still-running" T)
(log-kv "state-after-open" (state))
(safe "entities-after-open" (function (lambda () (sslength (ssget "_X")))))
(safe "documents-count"
  (function (lambda () (vla-get-count (vla-get-documents (vlax-get-acad-object))))))
(safe "active-doc-name"
  (function (lambda () (vla-get-name (vla-get-activedocument (vlax-get-acad-object))))))

;; Does the loop keep running and see the same document afterwards?
(repeat 3 (command "_.DELAY" 250))
(log-kv "after-delay" (state))
(safe "can-draw-after-open" (function (lambda () (add-line) (sslength (ssget "_X")))))
(finish)
