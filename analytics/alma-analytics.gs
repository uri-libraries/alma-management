function checkModificationAlert() {
  // --- User Modification Check ---
  var userSheet = spreadsheet.getSheetByName('UsersModifiedDaily'); // Change to your actual sheet name
  var modifiedUsers = 0;
  if (userSheet) {
    var userData = userSheet.getDataRange().getValues();
    modifiedUsers = userData.length - 1; // subtract header
  } else {
    Logger.log('Sheet "UsersModifiedDaily" not found. Skipping user modification check.');
  }

  // Get total users - look for total count in the report data itself
  var totalUsers = 0;
  
  // Option 1: If your report includes a "Total Users" column, get it from the first data row
  if (userSheet && userData.length > 1) {
    // Check if there's a "Total Users" or similar column (adjust column index as needed)
    var headers = userData[0];
    var totalUsersColumnIndex = headers.indexOf('Total Users'); // Adjust column name as needed
    if (totalUsersColumnIndex !== -1) {
      totalUsers = parseInt(userData[1][totalUsersColumnIndex]) || 0;
      Logger.log('Using Total Users column from report: ' + totalUsers);
    }
  }
  
  // Option 2: Fallback to separate sheets or static value
  if (totalUsers === 0) {
    var totalUserSheet = spreadsheet.getSheetByName('TotalUsers');
    if (totalUserSheet) {
      var totalUserData = totalUserSheet.getDataRange().getValues();
      totalUsers = totalUserData.length - 1;
      Logger.log('Using TotalUsers sheet for total count: ' + totalUsers);
    } else {
      totalUsers = 28745; // Replace with your actual Alma user count - check Alma Administration > User Management
      Logger.log('No total users data found. Using static value: ' + totalUsers);
    }
  }

  var percentUsers = totalUsers > 0 ? (modifiedUsers / totalUsers) * 100 : 0;

  // --- Inventory Modification Check ---
  var itemSheet = spreadsheet.getSheetByName('ItemsModifiedDaily'); // Change to your actual sheet name
  var modifiedItems = 0;
  if (itemSheet) {
    var itemData = itemSheet.getDataRange().getValues();
    modifiedItems = itemData.length > 0 ? itemData.length - 1 : 0;
  } else {
    Logger.log('Sheet "ItemsModifiedDaily" not found. Skipping item modification check.');
  }

  // Get total items - look for total count in the report data itself
  var totalItems = 0;
  
  // Option 1: If your report includes a "Total Items" column, get it from the first data row
  if (itemSheet && itemData.length > 1) {
    // Check if there's a "Total Items" or similar column (adjust column index as needed)
    var headers = itemData[0];
    var totalItemsColumnIndex = headers.indexOf('Total Items'); // Adjust column name as needed
    if (totalItemsColumnIndex !== -1) {
      totalItems = parseInt(itemData[1][totalItemsColumnIndex]) || 0;
      Logger.log('Using Total Items column from report: ' + totalItems);
    }
  }
  
  // Option 2: Fallback to separate sheets or static value
  if (totalItems === 0) {
    var totalItemSheet = spreadsheet.getSheetByName('TotalItems');
    if (totalItemSheet) {
      var totalItemData = totalItemSheet.getDataRange().getValues();
      totalItems = totalItemData.length - 1;
      Logger.log('Using TotalItems sheet for total count: ' + totalItems);
    } else {
      totalItems = 150000; // Update this to your actual total item count from Alma
      Logger.log('No total items data found. Using static value: ' + totalItems);
    }
  }

  var percentItems = totalItems > 0 ? (modifiedItems / totalItems) * 100 : 0;

  // --- Send Email Alert if threshold exceeded ---
  var alertMsg = '';
  if (percentUsers >= 5) {
    alertMsg += 'More than 5% of users were modified in the last day. (' + modifiedUsers + ' of ' + totalUsers + ')\n';
  }
  if (percentItems >= 5) {
    alertMsg += 'More than 5% of inventory items were modified in the last day. (' + modifiedItems + ' of ' + totalItems + ')\n';
  }
  if (alertMsg) {
    MailApp.sendEmail('your@email.com', 'Alma Modification Alert', alertMsg);
    // Send to SMS via email-to-SMS gateway
    MailApp.sendEmail('1234567890@carrier.com', '', alertMsg); // Replace with your SMS gateway address
  }
}

// MAIN FUNCTION TO RUN
function main() {
  var tableObj = {};
  try {
    var reports = loadConfig();
    for (var i = 0; i < reports.length; i++) {
      try {
        var tableData = callAnalyticsAPI(reports[i]);
        tableObj[reports[i].spreadsheetTab] = tableData;
      } catch (e) { 
        if (e == 'Query failed!') {
          Logger.log('Query failed on ' + reports[i].spreadsheetTab);      
          continue;
        } else {
          throw e;
        }
      }
    }
  } catch(e) {
    errorHandler(e);
  }
  sendToSpreadsheet(tableObj);
  checkModificationAlert(); // <-- Run the alert check after data import
}