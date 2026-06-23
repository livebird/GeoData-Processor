# Validation Rule Catalog

**Version:** 1.0.0  
**Last Updated:** 2026-06-23  
**Status:** Active  

This document catalogs all validation rules in the GeoData Processor system as required by FR-VAL-006. Each rule includes its error code, severity level, category, and description.

---

## Severity Levels

The system uses four severity levels to classify validation issues:

| Severity | Description | Dispatch Behavior |
|----------|-------------|-------------------|
| **critical** | System-level errors that prevent any operation | **Blocks dispatch** (FR-VAL-004) |
| **error** | Data or operation errors that invalidate the result | **Blocks dispatch** (FR-VAL-004) |
| **warning** | Non-critical issues that may affect quality | **Allows processing** (FR-VAL-005) |
| **info** | Informational messages for user awareness | **Allows processing** (FR-VAL-005) |

---

## Error Categories

| Category | Code | Description |
|----------|------|-------------|
| Validation | `validation` | File format, driver, and parameter validation |
| Conversion | `conversion` | Format conversion and transformation errors |
| Metadata | `metadata` | Metadata extraction and parsing errors |
| File I/O | `file_io` | File read/write and storage errors |
| Network | `network` | Remote file download and network errors |
| Database | `database` | Database connection and query errors |
| Permission | `permission` | Access control and privilege errors |
| Resource | `resource` | Resource availability and locking errors |

---

## Validation Rules

### VAL001 - Invalid File Format

| Field | Value |
|-------|-------|
| **Error Code** | `VAL001` |
| **Severity** | `error` |
| **Category** | `validation` |
| **Message** | The file format is not supported or invalid. |
| description | The uploaded or specified file does not match a supported GDAL format or has an invalid extension. |
| **Blocking** | Yes |

**Trigger Conditions:**
- File extension does not match expected driver extension
- File cannot be opened by GDAL
- File format is not in the supported drivers list

**Resolution:**
- Verify the file format is supported
- Check file extension matches the actual format
- Ensure file is not corrupted

---

### VAL002 - Unsupported Conversion

| Field | Value |
|-------|-------|
| **Error Code** | `VAL002` |
| **Severity** | `error` |
| **Category** | `validation` |
| **Message** | The requested conversion is not supported. |
| **Description** | The conversion pair (input driver to output driver) is not supported by the system. |
| **Blocking** | Yes |

**Trigger Conditions:**
- Input driver and output driver combination is not in the supported conversion matrix
- Conversion requires unsupported GDAL capabilities

**Resolution:**
- Check supported conversion pairs via `/api/v1/supported-conversions/`
- Select a different output format
- Verify both drivers are installed

---

### VAL003 - File Not Found

| Field | Value |
|-------|-------|
| **Error Code** | `VAL003` |
| **Severity** | `error` |
| **Category** | `validation` |
| **Message** | The specified file could not be found. |
| **Description** | The file path provided does not exist or is not accessible. |
| **Blocking** | Yes |

**Trigger Conditions:**
- File path does not exist on the filesystem
- File path is a directory when a file is expected
- File has been deleted or moved

**Resolution:**
- Verify the file path is correct
- Check file permissions
- Re-upload the file if necessary

---

### VAL004 - File Corrupted

| Field | Value |
|-------|-------|
| **Error Code** | `VAL004` |
| **Severity** | `error` |
| **Category** | `validation` |
| **Message** | The file appears to be corrupted or unreadable. |
| **Description** | GDAL cannot read the file due to corruption or invalid structure. |
| **Blocking** | Yes |

**Trigger Conditions:**
- GDAL fails to open the file
- File header is invalid
- File structure is damaged

**Resolution:**
- Verify file integrity
- Re-download or re-upload the file
- Check file transfer was complete

---

### VAL005 - Invalid Driver

| Field | Value |
|-------|-------|
| **Error Code** | `VAL005` |
| **Severity** | `error` |
| **Category** | `validation` |
| **Message** | The specified GDAL driver is invalid or not available. |
| **Description** | The requested GDAL driver is not installed or not supported. |
| **Blocking** | Yes |

**Trigger Conditions:**
- Driver name is not in the supported drivers list
- Driver is not installed in the GDAL installation
- Driver name is misspelled

**Resolution:**
- Check available drivers via `/api/v1/supported-conversions/`
- Install the required GDAL driver
- Verify driver name spelling

---

## Conversion Errors

### CONV001 - Conversion Failed

| Field | Value |
|-------|-------|
| **Error Code** | `CONV001` |
| **Severity** | `error` |
| **Category** | `conversion` |
| **Message** | The conversion operation failed. |
| **Description** | The format conversion process encountered an error and could not complete. |
| **Blocking** | Yes |

**Trigger Conditions:**
- Transformation service raised an exception
- Output file could not be written
- Conversion parameters are invalid

**Resolution:**
- Check conversion parameters
- Verify output directory is writable
- Review error details for specific cause

---

### CONV002 - GDAL Error

| Field | Value |
|-------|-------|
| **Error Code** | `CONV002` |
| **Severity** | `error` |
| **Category** | `conversion` |
| **Message** | A GDAL library error occurred during processing. |
| **Description** | The underlying GDAL library encountered an error during conversion. |
| **Blocking** | Yes |

**Trigger Conditions:**
- GDAL operation raised an exception
- GDAL configuration is invalid
- GDAL data files are missing

**Resolution:**
- Check GDAL installation
- Verify PROJ_LIB environment variable
- Review GDAL error logs

---

### CONV003 - Memory Limit Exceeded

| Field | Value |
|-------|-------|
| **Error Code** | `CONV003` |
| **Severity** | `error` |
| **Category** | `conversion` |
| **Message** | The operation exceeded available memory limits. |
| **Description** | The conversion required more memory than available. |
| **Blocking** | Yes |

**Trigger Conditions:**
- File is too large for available memory
- System memory is exhausted
- Memory limit configuration is too low

**Resolution:**
- Process smaller files
- Increase system memory
- Adjust memory limit configuration

---

### CONV004 - Timeout

| Field | Value |
|-------|-------|
| **Error Code** | `CONV004` |
| **Severity** | `error` |
| **Category** | `conversion` |
| **Message** | The operation timed out. |
| **Description** | The conversion operation took longer than the allowed timeout. |
| **Blocking** | Yes |

**Trigger Conditions:**
- Conversion exceeded configured timeout
- File is very large or complex
- System is under heavy load

**Resolution:**
- Increase timeout configuration
- Process smaller files
- Optimize conversion parameters

---

## Metadata Errors

### META001 - Metadata Extraction Failed

| Field | Value |
|-------|-------|
| **Error Code** | `META001` |
| **Severity** | `warning` |
| **Category** | `metadata` |
| **Message** | Failed to extract metadata from the file. |
| **Description** | ogrinfo or gdalinfo could not extract metadata from the file. |
| **Blocking** | No |

**Trigger Conditions:**
- ogrinfo/gdalinfo command failed
- File has non-standard metadata
- Metadata is corrupted

**Resolution:**
- Verify file is valid GDAL format
- Check ogrinfo/gdalinfo installation
- Metadata is optional for conversion

---

### META002 - Unsupported Metadata Format

| Field | Value |
|-------|-------|
| **Error Code** | `META002` |
| **Severity** | `info` |
| **Category** | `metadata` |
| **Message** | The metadata format is not supported. |
| **Description** | The file's metadata format is not recognized by the system. |
| **Blocking** | No |

**Trigger Conditions:**
- File uses non-standard metadata
- Metadata encoding is unusual
- Custom metadata fields present

**Resolution:**
- Metadata is informational only
- Conversion can proceed without metadata
- Consider standardizing metadata format

---

## File I/O Errors

### IO001 - Read Error

| Field | Value |
|-------|-------|
| **Error Code** | `IO001` |
| **Severity** | `error` |
| **Category** | `file_io` |
| **Message** | Failed to read the file. |
| **Description** | The system could not read the file from storage. |
| **Blocking** | Yes |

**Trigger Conditions:**
- File is locked by another process
- Storage device is unavailable
- File permissions prevent reading

**Resolution:**
- Check file permissions
- Ensure file is not in use
- Verify storage is accessible

---

### IO002 - Write Error

| Field | Value |
|-------|-------|
| **Error Code** | `IO002` |
| **Severity** | `error` |
| **Category** | `file_io` |
| **Message** | Failed to write the output file. |
| **Description** | The system could not write the output file to storage. |
| **Blocking** | Yes |

**Trigger Conditions:**
- Output directory is not writable
- Disk is full
- Storage quota exceeded

**Resolution:**
- Check output directory permissions
- Free disk space
- Verify storage quota

---

### IO003 - Disk Space Exceeded

| Field | Value |
|-------|-------|
| **Error Code** | `IO003` |
| **Severity** | `error` |
| **Category** | `file_io` |
| **Chessage** | Insufficient disk space for the operation. |
| **Description** | There is not enough disk space to complete the operation. |
| **Blocking** | Yes |

**Trigger Conditions:**
- Available disk space is less than required
- Output file would exceed available space
- Temporary files consume too much space

**Resolution:**
- Free disk space
- Use different output location
- Process smaller files

---

## Network Errors

### NET001 - Download Failed

| Field | Value |
|-------|-------|
| **Error Code** | `NET001` |
| **Severity** | `error` |
| **Category** | `network` |
| **Message** | Failed to download the remote file. |
| **Description** | The remote file could not be downloaded from the URL. |
| **Blocking** | Yes |

**Trigger Conditions:**
- URL is not accessible
- Server returned error response
- Network connection failed

**Resolution:**
- Verify URL is correct
- Check network connectivity
- Ensure server is accessible

---

### NET002 - Connection Timeout

| Field | Value |
|-------|-------|
| **Error Code** | `NET002` |
| **Severity** | `error` |
| **Category** | `network` |
| **Message** | Network connection timed out. |
| **Description** | The network connection timed out during download. |
| **Blocking** | Yes |

**Trigger Conditions:**
- Network is slow
- Server is not responding
- Firewall blocking connection

**Resolution:**
- Increase timeout configuration
- Check network connectivity
- Verify firewall settings

---

### NET003 - Invalid URL

| Field | Value |
|-------|-------|
| **Error Code** | `NET003` |
| **Severity** | `error` |
| **Category** | `network` |
| **Message** | The provided URL is invalid. |
| **Description** | The URL format is invalid or malformed. |
| **Blocking** | Yes |

**Trigger Conditions:**
- URL does not have a valid scheme
- URL is malformed
- URL contains invalid characters

**Resolution:**
- Verify URL format
- Use valid URL scheme (http, https, s3)
- Check for typos in URL

---

## Database Errors

### DB001 - Connection Error

| Field | Value |
|-------|-------|
| **Error Code** | `DB001` |
| **Severity** | `error` |
| **Category** | `database` |
| **Message** | Failed to connect to the database. |
| **Description** | Could not establish connection to the database. |
| **Blocking** | Yes |

**Trigger Conditions:**
- Database server is down
- Connection credentials are invalid
- Network cannot reach database

**Resolution:**
- Verify database server is running
- Check connection credentials
- Test network connectivity

---

### DB002 - Query Error

| Field | Value |
|-------|-------|
| **Error Code** | `DB002` |
| **Severity** | `error` |
| **Category** | `database` |
| **Message** | A database query error occurred. |
| **Description** | Database query execution failed. |
| **Blocking** | Yes |

**Trigger Conditions:**
- SQL query is invalid
- Table or column does not exist
- Database constraints violated

**Resolution:**
- Review query syntax
- Verify schema matches
- Check database constraints

---

## Permission Errors

### PERM001 - Access Denied

| Field | Value |
|-------|-------|
| **Error Code** | `PERM001` |
| **Severity** | `error` |
| **Category** | `permission` |
| **Message** | Access to the resource was denied. |
| **Description** | User does not have permission to access the resource. |
| **Blocking** | Yes |

**Trigger Conditions:**
- User lacks required permissions
- Resource is protected
- Authentication failed

**Resolution:**
- Check user permissions
- Authenticate properly
- Contact administrator

---

### PERM002 - Insufficient Privileges

| Field | Value |
|-------|-------|
| **Error Code** | `PERM002` |
| **Severity** | `error` |
| **Category** | `permission` |
| **Message** | Insufficient privileges to perform the operation. |
| **Description** | User does not have sufficient privileges for the operation. |
| **Blocking** | Yes |

**Trigger Conditions:**
- User role lacks required privileges
- Operation requires elevated access
- RBAC policy denies operation

**Resolution:**
- Check user role and privileges
- Request elevated privileges
- Contact administrator

---

## Resource Errors

### RES001 - Resource Not Found

| Field | Value |
|-------|-------|
| **Error Code** | `RES001` |
| **Severity** | `error` |
| **Category** | `resource` |
| **Message** | The requested resource was not found. |
| **Description** | The requested resource does not exist. |
| **Blocking** | Yes |

**Trigger Conditions:**
- Resource ID is invalid
- Resource was deleted
- Resource never existed

**Resolution:**
- Verify resource ID
- Check resource exists
- Use valid resource identifier

---

### RES002 - Resource Locked

| Field | Value |
|-------|-------|
| **Error Code** | `RES002` |
| **Severity** | `warning` |
| **Category** | `resource` |
| **Message** | The resource is currently locked and unavailable. |
| **Description** | The resource is locked by another operation. |
| **Blocking** | No |

**Trigger Conditions:**
- Resource is in use
- Another job is processing the resource
- Resource has an active lock

**Resolution:**
- Wait for lock to release
- Use different resource
- Cancel conflicting operation

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-06-23 | Initial version with all validation rules cataloged |

---

## References

- **SRS §4:** Technology Stack
- **SRS §7.2:** Metadata Extraction Requirements
- **FR-VAL-004:** Severity-based dispatch blocking
- **FR-VAL-005:** Non-blocking severity handling
- **FR-VAL-006:** Validation rule catalog documentation
