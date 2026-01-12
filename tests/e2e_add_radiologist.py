import urllib.parse, urllib.request, http.cookiejar, sys

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
base = 'http://127.0.0.1:8020'

try:
    login_data = urllib.parse.urlencode({'username':'admin','password':'admin123','role':'admin','next':'/settings'}).encode()
    req = urllib.request.Request(base+'/login', data=login_data)
    resp = opener.open(req)
    print('Login response URL:', resp.geturl())

    # fetch settings page
    req = urllib.request.Request(base+'/settings')
    html = opener.open(req).read().decode()
    print('Settings page length before add:', len(html))

    # add radiologist
    add_data = urllib.parse.urlencode({'name':'TestRad','surname':'Tester','gmc':'999999','email':'test@example.com'}).encode()
    req = urllib.request.Request(base+'/settings/radiologist/add', data=add_data)
    resp = opener.open(req)
    print('Add response URL:', resp.geturl())

    # fetch settings again
    html2 = opener.open(urllib.request.Request(base+'/settings')).read().decode()
    found = 'TestRad' in html2 and 'Tester' in html2 and '999999' in html2
    print('Found radiologist in settings:', found)
    if not found:
        print(html2[:2000])
except Exception as e:
    print('Error:', e)
    sys.exit(1)
