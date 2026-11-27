/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef TIHULU_LIVECAPTURE_H
#define TIHULU_LIVECAPTURE_H

#include <QFile>
#include <QFileInfo>
#include <QObject>

// Tee only the selected service's existing, filtered TS; never acquire a device.
// A stopped/silent service creates no empty recording. Existing files and
// partial output after an I/O failure are never overwritten or removed.
class LiveCapture {
public:
	bool begin(const QString &path) {
		if (armed || path.isEmpty() || QFileInfo::exists(path)) return false;
		file.setFileName(path);
		header.clear(); error.clear(); payload = 0; armed = true;
		return true;
	}
	bool active() const { return armed; }
	QString failure() const { return error; }
	void tables(const QByteArray &pat, const QByteArray &pmt) {
		if (!armed || !error.isEmpty() || pat.isEmpty() || pmt.isEmpty()) return;
		if (!file.isOpen()) header = pat + pmt;
		else { write(pat.constData(), pat.size()); write(pmt.constData(), pmt.size()); }
	}
	void packet(const char *data) {
		if (!armed || !error.isEmpty() || data[0] != 0x47) return;
		if (!file.isOpen()) {
			if (header.isEmpty() || !(data[3] & 0x10)) return;
			if (!file.open(QIODevice::WriteOnly | QIODevice::NewOnly)) { error = file.errorString(); return; }
			write(header.constData(), header.size());
		}
		if (write(data, 188)) payload += 188;
	}
	QString finish(QString &reason) {
		if (file.isOpen()) {
			if (!file.flush()) error = file.errorString();
			file.close();
		}
		armed = false;
		reason = error;
		if (reason.isEmpty() && !payload) reason = QObject::tr("No transport stream received; no recording saved.");
		return reason.isEmpty() ? file.fileName() : QString();
	}
private:
	bool write(const char *p, int size) {
		if (!error.isEmpty()) return false;
		if (file.write(p, size) == size) return true;
		error = file.errorString(); return false;
	}
	bool armed = false;
	qint64 payload = 0;
	QFile file;
	QByteArray header;
	QString error;
};
#endif
