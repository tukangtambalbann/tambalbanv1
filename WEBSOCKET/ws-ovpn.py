#!/usr/bin/python3
import socket, threading, select, signal, sys, time, getopt

# Listen
LISTENING_ADDR = '0.0.0.0'
# Mengatasi agar LISTENING_PORT memiliki nilai default jika tidak ada argumen
# Ini penting karena sys.argv[1] bisa saja tidak ada
LISTENING_PORT = 900 # Default port, akan ditimpa jika argumen diberikan

# Pass
PASS = ''

# CONST
BUFLEN = 4096 * 4
TIMEOUT = 60
DEFAULT_HOST = '127.0.0.1:109'
# String harus di-encode saat dikirim melalui socket
RESPONSE = b'HTTP/1.1 101 \x1b[32m!!.. Konek..cuyy..!!!\x1b[0m\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: foo\r\n\r\n'
# Catatan: Bagian HTML seperti <b><font color="green"> tidak akan berfungsi di sini,
# Karena ini adalah respons HTTP biasa, bukan konten web. Saya menggantinya
# dengan escape sequence ANSI untuk warna hijau jika terminal mendukungnya,
# atau Anda bisa menghapusnya sepenuhnya. Jika Anda ingin tampilan web,
# ini harus menjadi proxy web yang sebenarnya, bukan hanya websocket.
# Jika tujuannya hanya teks biasa, hilangkan tag HTML dan kode warna ANSI.
# Contoh: RESPONSE = b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: foo\r\n\r\n'

class Server(threading.Thread):
    def __init__(self, host, port):
        threading.Thread.__init__(self)
        self.running = False
        self.host = host
        self.port = port
        self.threads = []
        self.threadsLock = threading.Lock()
        self.logLock = threading.Lock()

    def run(self):
        self.soc = socket.socket(socket.AF_INET)
        self.soc.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.soc.settimeout(2)
        intport = int(self.port) # Pastikan port adalah integer
        try:
            self.soc.bind((self.host, intport))
        except OSError as e:
            # Tambahkan penanganan error bind agar lebih informatif
            self.printLog(f"Error: Could not bind to {self.host}:{self.port} - {e}")
            self.running = False
            return # Keluar dari thread jika bind gagal

        self.soc.listen(0)
        self.running = True

        try:
            while self.running:
                try:
                    c, addr = self.soc.accept()
                    c.setblocking(1)
                except socket.timeout:
                    continue

                conn = ConnectionHandler(c, self, addr)
                conn.start()
                self.addConn(conn)
        finally:
            self.running = False
            self.soc.close()

    def printLog(self, log):
        self.logLock.acquire()
        print(log) # Perbaikan: print sebagai fungsi
        self.logLock.release()

    def addConn(self, conn):
        try:
            self.threadsLock.acquire()
            if self.running:
                self.threads.append(conn)
        finally:
            self.threadsLock.release()

    def removeConn(self, conn):
        try:
            self.threadsLock.acquire()
            if conn in self.threads: # Pastikan koneksi ada sebelum mencoba menghapus
                self.threads.remove(conn)
        finally:
            self.threadsLock.release()

    def close(self):
        try:
            self.running = False
            self.threadsLock.acquire()

            threads = list(self.threads)
            for c in threads:
                c.close()
        finally:
            self.threadsLock.release()


class ConnectionHandler(threading.Thread):
    def __init__(self, socClient, server, addr):
        threading.Thread.__init__(self)
        self.clientClosed = False
        self.targetClosed = True
        self.client = socClient
        self.client_buffer = b'' # Default ke bytes karena recv mengembalikan bytes
        self.server = server
        self.log = 'Connection: ' + str(addr)

    def close(self):
        try:
            if not self.clientClosed:
                self.client.shutdown(socket.SHUT_RDWR)
                self.client.close()
        except:
            pass
        finally:
            self.clientClosed = True

        try:
            if not self.targetClosed:
                self.target.shutdown(socket.SHUT_RDWR)
                self.target.close()
        except:
            pass
        finally:
            self.targetClosed = True

    def run(self):
        try:
            self.client_buffer = self.client.recv(BUFLEN)
            
            # Mendekode buffer client untuk operasi string, lalu encode kembali saat mengirim
            client_buffer_str = self.client_buffer.decode('latin-1') # Pilih encoding yang sesuai, latin-1 sering dipakai untuk header HTTP

            hostPort = self.findHeader(client_buffer_str, 'X-Real-Host')

            if hostPort == '':
                hostPort = DEFAULT_HOST

            split = self.findHeader(client_buffer_str, 'X-Split')

            if split != '':
                self.client.recv(BUFLEN) # Buang sisa data, asumsi tidak digunakan

            if hostPort != '':
                passwd = self.findHeader(client_buffer_str, 'X-Pass')

                if len(PASS) != 0 and passwd == PASS:
                    self.method_CONNECT(hostPort)
                elif len(PASS) != 0 and passwd != PASS:
                    self.client.send(b'HTTP/1.1 400 WrongPass!\r\n\r\n') # String literal perlu di-encode
                elif hostPort.startswith('127.0.0.1') or hostPort.startswith('localhost'):
                    self.method_CONNECT(hostPort)
                else:
                    self.server.printLog('- No X-Real-Host! (Forbidden)') # Perbaikan: print sebagai fungsi
                    self.client.send(b'HTTP/1.1 403 Forbidden!\r\n\r\n') # String literal perlu di-encode
            else:
                self.server.printLog('- No X-Real-Host! (Bad Request)') # Perbaikan: print sebagai fungsi
                self.client.send(b'HTTP/1.1 400 NoXRealHost!\r\n\r\n') # String literal perlu di-encode

        except Exception as e:
            # Gunakan str(e) untuk mendapatkan representasi string dari objek pengecualian
            self.log += ' - error: ' + str(e)
            self.server.printLog(self.log)
            # Tidak perlu `pass` jika sudah ada kode di sini
        finally:
            self.close()
            self.server.removeConn(self)

    def findHeader(self, head, header):
        # Header harus dicari di string yang sudah didekode
        aux = head.find(header + ': ')

        if aux == -1:
            return ''

        aux = head.find(':', aux)
        head = head[aux+2:]
        aux = head.find('\r\n')

        if aux == -1:
            return ''

        return head[:aux]

    def connect_target(self, host):
        i = host.find(':')
        if i != -1:
            port = int(host[i+1:])
            host = host[:i]
        else:
            # Gunakan self.method jika didefinisikan, jika tidak, gunakan string 'CONNECT'
            # Karena self.method belum tentu ada, perlu penanganan
            if hasattr(self, 'method') and self.method=='CONNECT':
                port = 443
            else:
                # Menggunakan LISTENING_PORT sebagai target fallback adalah aneh untuk proxy
                # Biasanya proxy akan target ke port default dari protokol tujuan (misal 80/443)
                # Saya mengembalikan ke DEFAULT_HOST atau logika asli yang lebih aman.
                # Mengacu pada baris 32 di `ws-stunnel` yang Anda berikan sebelumnya,
                # port diambil dari sys.argv[1] jika ada, jika tidak default 700.
                # Logika di sini agak berbeda dari ws-stunnel.
                # Jika tujuannya adalah OpenVPN, port target haruslah port OpenVPN.
                # DEFAULT_HOST sudah '127.0.0.1:109' yang sepertinya port OpenVPN/SSH target.
                port = int(LISTENING_PORT) # Mengambil port dari LISTENING_PORT skrip
                # Jika sys.argv[1] digunakan sebagai port koneksi target (bukan port listen),
                # ini tidak masuk akal untuk proxy normal. Ini mungkin khusus untuk konfigurasi Anda.

        (soc_family, soc_type, proto, _, address) = socket.getaddrinfo(host, port)[0]

        self.target = socket.socket(soc_family, soc_type, proto)
        self.targetClosed = False
        self.target.connect(address)

    def method_CONNECT(self, path):
        self.log += ' - CONNECT ' + path

        self.connect_target(path)
        self.client.sendall(RESPONSE) # RESPONSE sudah berupa bytes (b'')
        self.client_buffer = b'' # Default ke bytes

        self.server.printLog(self.log)
        self.doCONNECT()

    def doCONNECT(self):
        socs = [self.client, self.target]
        count = 0
        error = False
        while True:
            count += 1
            (recv, _, err) = select.select(socs, [], socs, 3)
            if err:
                error = True
            if recv:
                for in_ in recv:
                    try:
                        data = in_.recv(BUFLEN)
                        if data:
                            if in_ is self.target:
                                self.client.send(data)
                            else:
                                while data:
                                    byte = self.target.send(data)
                                    data = data[byte:]

                            count = 0
                        else:
                            break # Koneksi ditutup oleh salah satu pihak
                    except Exception as e:
                        self.server.printLog(f"Error in doCONNECT: {e}") # Debugging
                        error = True
                        break
            if count == TIMEOUT:
                error = True
            if error:
                break


def print_usage():
    print('Usage: proxy.py -p <port>') # Perbaikan: print sebagai fungsi
    print('          proxy.py -b <bindAddr> -p <port>') # Perbaikan: print sebagai fungsi
    print('          proxy.py -b 0.0.0.0 -p 80') # Perbaikan: print sebagai fungsi

def parse_args(argv):
    global LISTENING_ADDR
    global LISTENING_PORT

    try:
        opts, args = getopt.getopt(argv,"hb:p:",["bind=","port="])
    except getopt.GetoptError:
        print_usage()
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print_usage()
            sys.exit()
        elif opt in ("-b", "--bind"):
            LISTENING_ADDR = arg
        elif opt in ("-p", "--port"):
            LISTENING_PORT = int(arg)


def main(): # Menghapus parameter default karena mereka global
    parse_args(sys.argv[1:]) # Panggil parse_args untuk memproses argumen baris perintah
    
    print("\n:-------PythonProxy-------:\n") # Perbaikan: print sebagai fungsi
    print("Listening addr: " + LISTENING_ADDR) # Perbaikan: print sebagai fungsi
    print("Listening port: " + str(LISTENING_PORT) + "\n") # Perbaikan: print sebagai fungsi
    print(":-------------------------:\n") # Perbaikan: print sebagai fungsi
    
    server = Server(LISTENING_ADDR, LISTENING_PORT)
    server.start()
    
    # Menunggu thread server utama selesai
    while server.running: # Loop selama server.running masih True
        try:
            time.sleep(2)
        except KeyboardInterrupt:
            print('Stopping...') # Perbaikan: print sebagai fungsi
            server.close()
            break
        except Exception as e:
            print(f"Main loop error: {e}")
            break

if __name__ == '__main__':
    main()
